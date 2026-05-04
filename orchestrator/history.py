"""
Persistent Q&A history for the DSA Agent.

Two parallel stores, both append-only and fully local:

1. SQLite database at ~/.dsa_agent/history.db
   - Structured columns: id, ts, platform, query, response, tools_json,
     rag_sources_json, latency_ms
   - FTS5 virtual table for fast full-text search across query + response
   - Powers /history, /search, /replay

2. Daily markdown files at ~/Downloads/dsa-history/YYYY-MM-DD.md
   - Human-browsable; greppable with any text tool
   - Each turn separated by a horizontal rule and timestamped heading

Both locations are configurable via DSA_HISTORY_DB and DSA_HISTORY_MD_DIR.
History recording is disabled if DSA_HISTORY=0 or if --no-history is passed
to the CLI.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from orchestrator.exporter import format_turn


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))


def default_db_path() -> Path:
    override = os.environ.get("DSA_HISTORY_DB")
    if override:
        return Path(override)
    return _home() / ".dsa_agent" / "history.db"


def default_md_dir() -> Path:
    override = os.environ.get("DSA_HISTORY_MD_DIR")
    if override:
        return Path(override)
    return _home() / "Downloads" / "dsa-history"


# ---------------------------------------------------------------------------
# History store
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT    NOT NULL,
    platform         TEXT,
    query            TEXT    NOT NULL,
    response         TEXT    NOT NULL,
    tools_json       TEXT,
    rag_sources_json TEXT,
    latency_ms       INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    query, response, platform UNINDEXED, content='turns', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, query, response, platform)
    VALUES (new.id, new.query, new.response, new.platform);
END;
"""


class History:
    """Append-only Q&A store backed by SQLite + daily markdown."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        md_dir: Optional[Path] = None,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.md_dir  = Path(md_dir)  if md_dir  else default_md_dir()
        self._conn: sqlite3.Connection | None = None

        if self.enabled:
            self._init_storage()

    # ---- internals ----

    def _init_storage(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.md_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---- public API ----

    def append(self, query: str, result: dict) -> Optional[int]:
        """
        Record a turn to both SQLite and today's markdown file.
        Returns the turn id, or None if history is disabled / write failed.
        """
        if not self.enabled or self._conn is None:
            return None

        ts       = datetime.now().isoformat(timespec="seconds")
        platform = result.get("platform", "unknown")
        response = result.get("response", "") or ""
        tools    = result.get("tool_calls_made", []) or []
        sources  = result.get("rag_sources", []) or []
        latency  = int(result.get("latency_ms", 0) or 0)

        try:
            cur = self._conn.execute(
                """INSERT INTO turns
                   (ts, platform, query, response, tools_json, rag_sources_json, latency_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts, platform, query, response,
                    json.dumps(tools, default=str),
                    json.dumps(sources, default=str),
                    latency,
                ),
            )
            self._conn.commit()
            turn_id = cur.lastrowid
        except sqlite3.Error:
            return None

        # Mirror to today's markdown file (best-effort; never fatal)
        try:
            self._append_markdown(turn_id, ts, query, result)
        except Exception:
            pass

        return turn_id

    def _append_markdown(self, turn_id: int, ts: str, query: str, result: dict) -> None:
        date = ts.split("T", 1)[0]
        path = self.md_dir / f"{date}.md"
        platform = result.get("platform", "unknown")
        latency  = result.get("latency_ms", 0)
        body = result.get("response", "") or ""

        # First entry of the day gets a date heading
        new_file = not path.exists()
        with path.open("a", encoding="utf-8") as fh:
            if new_file:
                fh.write(f"# DSA Agent history — {date}\n\n")
            fh.write("---\n\n")
            fh.write(f"## #{turn_id} · {ts} · {platform} · {latency}ms\n\n")
            fh.write(f"**Q:** {query.strip()}\n\n")
            fh.write(f"**A:**\n\n{body.strip()}\n\n")

    def recent(self, limit: int = 10) -> list[dict]:
        """Return the most recent N turns, newest first."""
        if not self.enabled or self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        Full-text search across query + response. Returns newest match first.
        Falls back to LIKE if FTS5 isn't available.
        """
        if not self.enabled or self._conn is None or not keyword.strip():
            return []
        try:
            rows = self._conn.execute(
                """SELECT t.* FROM turns t
                   JOIN turns_fts f ON f.rowid = t.id
                   WHERE turns_fts MATCH ?
                   ORDER BY t.id DESC LIMIT ?""",
                (keyword, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS5 might not be compiled in. Fall back to LIKE.
            like = f"%{keyword}%"
            rows = self._conn.execute(
                """SELECT * FROM turns
                   WHERE query LIKE ? OR response LIKE ?
                   ORDER BY id DESC LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get(self, turn_id: int) -> Optional[dict]:
        """Fetch a single turn by id (None if not found / disabled)."""
        if not self.enabled or self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT * FROM turns WHERE id = ?", (turn_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None

    def count(self) -> int:
        if not self.enabled or self._conn is None:
            return 0
        row = self._conn.execute("SELECT COUNT(*) AS c FROM turns").fetchone()
        return int(row["c"]) if row else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite Row into the dict shape callers expect."""
    return {
        "id":          row["id"],
        "ts":          row["ts"],
        "platform":    row["platform"],
        "query":       row["query"],
        "response":    row["response"],
        "tools":       _safe_json(row["tools_json"]),
        "rag_sources": _safe_json(row["rag_sources_json"]),
        "latency_ms":  row["latency_ms"] or 0,
    }


def _safe_json(s: Optional[str]) -> list:
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def turn_to_result(turn: dict) -> dict:
    """Convert a stored turn back into the result-dict shape used by exporter."""
    return {
        "platform":        turn.get("platform", "unknown"),
        "response":        turn.get("response", ""),
        "tool_calls_made": turn.get("tools", []),
        "rag_sources":     turn.get("rag_sources", []),
        "latency_ms":      turn.get("latency_ms", 0),
    }


def format_full_markdown(turn: dict) -> str:
    """Render a stored turn as a full self-contained markdown document."""
    return format_turn(turn.get("query", ""), turn_to_result(turn))
