"""
rag/refresher.py — Keep the RAG corpus current via GitHub SHA tracking.

How it works
------------
Every doc source maps to a specific path inside a PUBLIC GitHub repo.
On each run the script calls the GitHub commits API to get the latest
commit SHA that touched that path.  It compares against the SHA stored
in rag/.doc_versions.json from the previous ingest.  If the SHA changed
(or --force is given) it re-downloads the affected files and re-ingests
only that platform's ChromaDB collection.

No credentials required
-----------------------
All repos used (delta-io/delta, snowflakedb/*, Snowflake-Labs/sfquickstarts,
boto/botocore, awsdocs/*) are PUBLIC.  GitHub's unauthenticated REST API
allows 60 requests/hour — more than enough for a weekly scheduled run.
Set GITHUB_TOKEN in .env to raise the limit to 5 000/hour.

Graceful offline behaviour
--------------------------
Every network call is wrapped in a try/except with a short timeout.
If the machine is offline the script logs a warning and exits cleanly
without touching the existing corpus.

CLI
---
    python -m rag.refresher                # check all, re-ingest if changed
    python -m rag.refresher --platform aws
    python -m rag.refresher --force        # re-ingest regardless of SHA
    python -m rag.refresher --check-only   # print status table, no changes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE = Path(__file__).parent.parent   # repo root
_VERSIONS_FILE = _BASE / "rag" / ".doc_versions.json"
_DOCS_ROOT = _BASE / "rag" / "docs"
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_REQUEST_TIMEOUT = 15  # seconds per HTTP call

# ---------------------------------------------------------------------------
# Doc source registry
#
# Each entry describes one "unit" whose staleness is tracked by a single
# GitHub commit SHA.  Types:
#   github_dir   — list all files in a repo directory, download matching exts
#   github_file  — download a single file
#   botocore_svc — fetch botocore/data/<svc>/service-2.json, convert to text
# ---------------------------------------------------------------------------

DOC_SOURCES: dict[str, list[dict]] = {
    "databricks": [
        {
            "id":         "delta-lake-docs",
            "repo":       "delta-io/delta",
            "track_path": "docs/src/content/docs",
            "type":       "github_dir",
            "raw_base":   "https://raw.githubusercontent.com/delta-io/delta/master/docs/src/content/docs",
            "extensions": [".mdx", ".md"],
            "max_files":  40,
            "out_dir":    "databricks",
        },
    ],
    "snowflake": [
        {
            "id":         "snowflake-connector-python",
            "repo":       "snowflakedb/snowflake-connector-python",
            "track_path": "README.md",
            "type":       "github_file",
            "raw_url":    "https://raw.githubusercontent.com/snowflakedb/snowflake-connector-python/main/README.md",
            "out_dir":    "snowflake",
            "out_name":   "connector_python_readme.md",
        },
        {
            "id":         "snowpark-python",
            "repo":       "snowflakedb/snowpark-python",
            "track_path": "README.md",
            "type":       "github_file",
            "raw_url":    "https://raw.githubusercontent.com/snowflakedb/snowpark-python/main/README.md",
            "out_dir":    "snowflake",
            "out_name":   "snowpark_python_readme.md",
        },
        {
            "id":         "sfguide-python-api",
            "repo":       "Snowflake-Labs/sfquickstarts",
            "track_path": "site/sfguides/src/getting-started-snowflake-python-api",
            "type":       "github_file",
            "raw_url":    "https://raw.githubusercontent.com/Snowflake-Labs/sfquickstarts/master/site/sfguides/src/getting-started-snowflake-python-api/getting-started-snowflake-python-api.md",
            "out_dir":    "snowflake",
            "out_name":   "getting_started_python_api.md",
        },
        {
            "id":         "sfguide-snowpark-de",
            "repo":       "Snowflake-Labs/sfquickstarts",
            "track_path": "site/sfguides/src/data-engineering-with-snowpark-python-intro",
            "type":       "github_file",
            "raw_url":    "https://raw.githubusercontent.com/Snowflake-Labs/sfquickstarts/master/site/sfguides/src/data-engineering-with-snowpark-python-intro/data-engineering-with-snowpark-python-intro.md",
            "out_dir":    "snowflake",
            "out_name":   "data_engineering_snowpark.md",
        },
        {
            "id":         "sfguide-iceberg",
            "repo":       "Snowflake-Labs/sfquickstarts",
            "track_path": "site/sfguides/src/getting-started-iceberg-tables",
            "type":       "github_file",
            "raw_url":    "https://raw.githubusercontent.com/Snowflake-Labs/sfquickstarts/master/site/sfguides/src/getting-started-iceberg-tables/getting-started-iceberg-tables.md",
            "out_dir":    "snowflake",
            "out_name":   "iceberg_tables.md",
        },
    ],
    "aws": [
        {
            "id":         "botocore-s3",
            "repo":       "boto/botocore",
            "track_path": "botocore/data/s3",
            "type":       "botocore_svc",
            "service":    "s3",
            "raw_url":    "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/s3/2006-03-01/service-2.json.gz",
            "raw_url_plain": "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/s3/2006-03-01/service-2.json",
            "out_dir":    "aws",
            "out_name":   "botocore_s3.txt",
        },
        {
            "id":         "botocore-glue",
            "repo":       "boto/botocore",
            "track_path": "botocore/data/glue",
            "type":       "botocore_svc",
            "service":    "glue",
            "raw_url_plain": "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/glue/2017-03-31/service-2.json",
            "out_dir":    "aws",
            "out_name":   "botocore_glue.txt",
        },
        {
            "id":         "botocore-bedrock-runtime",
            "repo":       "boto/botocore",
            "track_path": "botocore/data/bedrock-runtime",
            "type":       "botocore_svc",
            "service":    "bedrock-runtime",
            "raw_url_plain": "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/bedrock-runtime/2023-09-30/service-2.json",
            "out_dir":    "aws",
            "out_name":   "botocore_bedrock_runtime.txt",
        },
        {
            "id":         "botocore-lambda",
            "repo":       "boto/botocore",
            "track_path": "botocore/data/lambda",
            "type":       "botocore_svc",
            "service":    "lambda",
            "raw_url_plain": "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/lambda/2015-03-31/service-2.json",
            "out_dir":    "aws",
            "out_name":   "botocore_lambda.txt",
        },
        {
            "id":         "botocore-iam",
            "repo":       "boto/botocore",
            "track_path": "botocore/data/iam",
            "type":       "botocore_svc",
            "service":    "iam",
            "raw_url_plain": "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/iam/2010-05-08/service-2.json",
            "out_dir":    "aws",
            "out_name":   "botocore_iam.txt",
        },
        {
            "id":         "botocore-ec2",
            "repo":       "boto/botocore",
            "track_path": "botocore/data/ec2",
            "type":       "botocore_svc",
            "service":    "ec2",
            "raw_url_plain": "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/ec2/2016-11-15/service-2.json",
            "out_dir":    "aws",
            "out_name":   "botocore_ec2.txt",
        },
        {
            "id":         "awsdocs-s3",
            "repo":       "awsdocs/amazon-s3-userguide",
            "track_path": "doc_source",
            "type":       "github_dir",
            "raw_base":   "https://raw.githubusercontent.com/awsdocs/amazon-s3-userguide/main/doc_source",
            "extensions": [".md", ".rst"],
            "max_files":  30,
            "out_dir":    "aws",
        },
        {
            "id":         "awsdocs-glue",
            "repo":       "awsdocs/aws-glue-developer-guide",
            "track_path": "doc_source",
            "type":       "github_dir",
            "raw_base":   "https://raw.githubusercontent.com/awsdocs/aws-glue-developer-guide/master/doc_source",
            "extensions": [".md", ".rst"],
            "max_files":  30,
            "out_dir":    "aws",
        },
    ],
}

PLATFORMS = list(DOC_SOURCES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _strip_html(s: str) -> str:
    p = _HTMLStripper()
    p.feed(s)
    return p.text()


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    if _GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {_GITHUB_TOKEN}"
    return h


def _fetch(url: str, timeout: int = _REQUEST_TIMEOUT) -> bytes | None:
    """Fetch URL bytes; return None on any network error."""
    try:
        req = urllib.request.Request(url, headers=_gh_headers())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as exc:
        print(f"  [warn] fetch failed: {url} — {exc}")
        return None


def _fetch_json(url: str) -> Any | None:
    raw = _fetch(url)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception as exc:
        print(f"  [warn] JSON parse failed: {url} — {exc}")
        return None


# ---------------------------------------------------------------------------
# Version store
# ---------------------------------------------------------------------------

def _load_versions() -> dict[str, dict]:
    if _VERSIONS_FILE.exists():
        try:
            return json.loads(_VERSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_versions(versions: dict[str, dict]) -> None:
    _VERSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _VERSIONS_FILE.write_text(
        json.dumps(versions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# SHA tracking
# ---------------------------------------------------------------------------

def _get_latest_sha(repo: str, path: str) -> str | None:
    """Return the commit SHA of the most recent commit touching `path`."""
    url = (f"https://api.github.com/repos/{repo}/commits"
           f"?path={path}&per_page=1")
    data = _fetch_json(url)
    if not data or not isinstance(data, list) or not data:
        return None
    return data[0].get("sha")


# ---------------------------------------------------------------------------
# Fetch strategies
# ---------------------------------------------------------------------------

def _fetch_github_dir(src: dict, out_root: Path) -> list[Path]:
    """List a GitHub directory and download matching files."""
    out_dir = out_root / src["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    api_url = (f"https://api.github.com/repos/{src['repo']}"
               f"/contents/{src['track_path']}")
    listing = _fetch_json(api_url)
    if not listing or not isinstance(listing, list):
        print(f"  [warn] could not list {src['repo']}/{src['track_path']}")
        return []

    exts = {e.lower() for e in src.get("extensions", [".md"])}
    files = [f for f in listing
             if f.get("type") == "file"
             and Path(f["name"]).suffix.lower() in exts]

    max_files = src.get("max_files", 50)
    files = files[:max_files]

    written: list[Path] = []
    for f in files:
        raw_url = f"{src['raw_base']}/{f['name']}"
        content = _fetch(raw_url)
        if content is None:
            continue
        dest = out_dir / f["name"]
        dest.write_bytes(content)
        written.append(dest)
        time.sleep(0.1)   # be polite to GitHub

    return written


def _fetch_github_file(src: dict, out_root: Path) -> list[Path]:
    """Download a single file."""
    out_dir = out_root / src["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    content = _fetch(src["raw_url"])
    if content is None:
        return []
    dest = out_dir / src["out_name"]
    dest.write_bytes(content)
    return [dest]


def _botocore_svc_to_text(service_name: str, raw_json: bytes) -> str:
    """
    Convert a botocore service-2.json into a clean, readable text document
    suitable for embedding.  Extracts every operation name + documentation.
    """
    try:
        data = json.loads(raw_json)
    except Exception:
        return ""

    lines: list[str] = [
        f"# AWS {service_name.upper()} — API Reference",
        f"# Source: boto/botocore (service-2.json)",
        "",
    ]

    meta = data.get("metadata", {})
    if meta:
        lines += [
            f"Service:    {meta.get('serviceFullName', service_name)}",
            f"Protocol:   {meta.get('protocol', '?')}",
            f"API version:{meta.get('apiVersion', '?')}",
            "",
        ]

    ops = data.get("operations", {})
    for op_name, op in sorted(ops.items()):
        doc_raw = op.get("documentation", "")
        doc = _strip_html(doc_raw).strip()
        http = op.get("http", {})
        method = http.get("method", "")
        uri = http.get("requestUri", "")

        # Required input members
        input_shape = op.get("input", {}).get("shape", "")
        shapes = data.get("shapes", {})
        required: list[str] = []
        if input_shape and input_shape in shapes:
            required = shapes[input_shape].get("required", [])

        lines.append(f"## {op_name}")
        if method:
            lines.append(f"HTTP: {method} {uri}")
        if required:
            lines.append(f"Required params: {', '.join(required)}")
        if doc:
            # Keep first 400 chars to avoid bloat
            lines.append(doc[:400] + ("..." if len(doc) > 400 else ""))
        lines.append("")

    return "\n".join(lines)


def _fetch_botocore_svc(src: dict, out_root: Path) -> list[Path]:
    """Fetch botocore service-2.json and convert to readable text."""
    out_dir = out_root / src["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_url = src.get("raw_url_plain") or src.get("raw_url")
    raw = _fetch(raw_url)
    if raw is None:
        return []

    text = _botocore_svc_to_text(src["service"], raw)
    if not text:
        return []

    dest = out_dir / src["out_name"]
    dest.write_text(text, encoding="utf-8")
    return [dest]


# ---------------------------------------------------------------------------
# Core refresh logic
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def refresh_source(src: dict, versions: dict, force: bool = False,
                   check_only: bool = False) -> dict:
    """
    Check and optionally refresh one doc source.
    Returns a status dict summarising what happened.
    """
    sid = src["id"]
    stored = versions.get(sid, {})
    stored_sha = stored.get("sha", "")

    # 1 — get latest SHA from GitHub
    latest_sha = _get_latest_sha(src["repo"], src["track_path"])
    if latest_sha is None:
        return {"id": sid, "status": "network_error",
                "stored_sha": stored_sha, "latest_sha": None}

    changed = (latest_sha != stored_sha)
    status = "changed" if changed else "up_to_date"

    if check_only:
        return {"id": sid, "status": status,
                "stored_sha": stored_sha[:10] if stored_sha else "none",
                "latest_sha": latest_sha[:10],
                "last_ingested": stored.get("last_ingested", "never")}

    if not changed and not force:
        return {"id": sid, "status": "up_to_date",
                "stored_sha": stored_sha[:10], "latest_sha": latest_sha[:10]}

    # 2 — fetch new content
    print(f"  Fetching {sid} ({'changed' if changed else 'forced'})...")
    out_root = _DOCS_ROOT
    fetch_fn = {
        "github_dir":  _fetch_github_dir,
        "github_file": _fetch_github_file,
        "botocore_svc": _fetch_botocore_svc,
    }.get(src["type"])

    if fetch_fn is None:
        return {"id": sid, "status": "unknown_type"}

    written = fetch_fn(src, out_root)
    if not written:
        return {"id": sid, "status": "fetch_failed"}

    # 3 — update version store (ingest happens per-platform after all sources run)
    versions[sid] = {
        "sha":           latest_sha,
        "last_checked":  _now_iso(),
        "last_ingested": _now_iso(),
        "files":         [str(p.relative_to(_BASE)) for p in written],
    }

    return {"id": sid, "status": "fetched",
            "files_written": len(written),
            "latest_sha": latest_sha[:10]}


def refresh_platform(platform: str, versions: dict, force: bool = False,
                     check_only: bool = False) -> list[dict]:
    sources = DOC_SOURCES.get(platform, [])
    if not sources:
        print(f"Unknown platform: {platform}")
        return []

    results: list[dict] = []
    needs_ingest = False

    for src in sources:
        r = refresh_source(src, versions, force=force, check_only=check_only)
        results.append(r)
        if r["status"] in ("fetched",):
            needs_ingest = True

    if not check_only and needs_ingest:
        print(f"  Re-ingesting {platform} into ChromaDB...")
        try:
            from rag.ingestor import ingest_platform_docs
            count = ingest_platform_docs(platform, force=True)
            print(f"  Ingested {count} chunks into cloud_agents_{platform}")
        except Exception as exc:
            print(f"  [error] ingest failed: {exc}")

    return results


# ---------------------------------------------------------------------------
# Pretty status table
# ---------------------------------------------------------------------------

def _print_table(all_results: dict[str, list[dict]]) -> None:
    try:
        from rich.table import Table
        from rich.console import Console
        console = Console()
        t = Table(title="RAG Corpus Status")
        t.add_column("Platform", style="cyan")
        t.add_column("Source ID")
        t.add_column("Status")
        t.add_column("Stored SHA")
        t.add_column("Latest SHA")
        t.add_column("Last Ingested")

        colours = {
            "up_to_date":    "green",
            "changed":       "yellow",
            "fetched":       "blue",
            "fetch_failed":  "red",
            "network_error": "red",
        }
        for platform, results in all_results.items():
            for r in results:
                colour = colours.get(r["status"], "white")
                t.add_row(
                    platform,
                    r["id"],
                    f"[{colour}]{r['status']}[/{colour}]",
                    r.get("stored_sha", "none"),
                    r.get("latest_sha", "?"),
                    r.get("last_ingested", "—"),
                )
        console.print(t)
    except ImportError:
        # Fallback plain text
        header = f"{'Platform':<12} {'Source ID':<35} {'Status':<15} {'Latest SHA'}"
        print(header)
        print("-" * len(header))
        for platform, results in all_results.items():
            for r in results:
                print(f"{platform:<12} {r['id']:<35} {r['status']:<15} "
                      f"{r.get('latest_sha', '?')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Keep DSA Agent RAG corpus current via GitHub SHA tracking."
    )
    parser.add_argument(
        "--platform",
        choices=PLATFORMS,
        help="Refresh a single platform (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch and re-ingest even if SHA is unchanged",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Show status table without downloading or ingesting anything",
    )
    args = parser.parse_args()

    versions = _load_versions()
    targets = [args.platform] if args.platform else PLATFORMS
    all_results: dict[str, list[dict]] = {}

    for platform in targets:
        print(f"\n[{platform}]")
        results = refresh_platform(
            platform, versions,
            force=args.force,
            check_only=args.check_only,
        )
        all_results[platform] = results

    if not args.check_only:
        _save_versions(versions)
        print("\nVersion store updated.")

    print()
    _print_table(all_results)


if __name__ == "__main__":
    main()
