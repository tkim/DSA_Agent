"""
Markdown exporter for agent responses.

Pure functions: format a Q->A turn into a self-contained markdown document
with YAML frontmatter capturing platform, latency, tool calls, and RAG sources.
No I/O — the caller writes to disk or pipes to the clipboard.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def _yaml_escape(s: str) -> str:
    """Minimal YAML scalar escaping — wraps in double quotes if needed."""
    if not s:
        return '""'
    if any(c in s for c in ':#\n"\\') or s.strip() != s:
        return json.dumps(s)  # JSON strings are valid YAML double-quoted scalars
    return s


def _frontmatter(query: str, result: dict) -> str:
    platform = result.get("platform", "unknown")
    latency  = result.get("latency_ms", 0)
    tools    = result.get("tool_calls_made", []) or []
    sources  = result.get("rag_sources", []) or []

    tool_names = [t.get("name", "?") for t in tools]
    lines = [
        "---",
        f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
        f"platform: {platform}",
        f"latency_ms: {latency}",
        f"tools: [{', '.join(tool_names)}]",
    ]
    if sources:
        lines.append("rag_sources:")
        for s in sources:
            src = str(s.get("source", "")).replace("\\", "/")
            score = s.get("score", 0.0)
            lines.append(f"  - {src} (score={score:.2f})")
    else:
        lines.append("rag_sources: []")

    # Multi-line query block
    lines.append("query: |")
    for ln in query.splitlines() or [query]:
        lines.append(f"  {ln}")
    lines.append("---")
    return "\n".join(lines)


def _tool_appendix(tools: list) -> str:
    if not tools:
        return ""
    parts = ["", "## Tool calls", ""]
    for i, t in enumerate(tools, 1):
        name = t.get("name", "?")
        args = t.get("args", {})
        result = t.get("result", {})
        parts.append(f"### {i}. `{name}`")
        parts.append("")
        parts.append(f"**Args:** `{json.dumps(args, default=str)}`")
        parts.append("")
        parts.append("**Result:**")
        parts.append("")
        parts.append("```json")
        parts.append(json.dumps(result, indent=2, default=str))
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def format_turn(query: str, result: dict) -> str:
    """Render a single Q->A turn as a self-contained markdown document."""
    body = result.get("response", "") or ""
    return (
        _frontmatter(query, result)
        + "\n\n# Query\n\n"
        + query.strip()
        + "\n\n# Response\n\n"
        + body.strip()
        + "\n"
        + _tool_appendix(result.get("tool_calls_made", []) or [])
    )


def downloads_dir() -> Path:
    """
    Return the user's Downloads folder. Honors USERPROFILE on Windows
    and falls back to ~/Downloads elsewhere. Creates if missing.
    """
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    d = home / "Downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """Return a path that does not collide with an existing file."""
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def default_filename(result: dict) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    platform = result.get("platform", "agent")
    return f"dsa-{platform}-{ts}"


def save_turn(query: str, result: dict, filename: str | None = None) -> Path:
    """Write a turn to the user's Downloads folder. Returns final path."""
    stem = filename or default_filename(result)
    # Strip any trailing .md the user supplied — unique_path adds it
    if stem.lower().endswith(".md"):
        stem = stem[:-3]
    path = unique_path(downloads_dir(), stem)
    path.write_text(format_turn(query, result), encoding="utf-8")
    return path


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to the system clipboard. Returns True on success.
    Uses Windows `clip`, macOS `pbcopy`, or Linux `xclip`/`xsel` if available.
    """
    import shutil
    import subprocess

    candidates = []
    if os.name == "nt":
        candidates.append(["clip"])
    else:
        if shutil.which("pbcopy"):
            candidates.append(["pbcopy"])
        if shutil.which("xclip"):
            candidates.append(["xclip", "-selection", "clipboard"])
        if shutil.which("xsel"):
            candidates.append(["xsel", "--clipboard", "--input"])

    for cmd in candidates:
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
    return False
