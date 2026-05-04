"""
Cloud Platform Agent — interactive CLI.

Usage:
    python cli.py                  # auto-route every query
    python cli.py --platform aws   # lock to one platform

Commands (type during chat):
    /platform auto|databricks|snowflake|aws   switch platform
    /save [filename]                          save last response to Downloads as .md
    /copy                                     copy last response (raw markdown) to clipboard
    /history [N]                              list the last N persisted turns (default 10)
    /search <keyword>                         full-text search across all past Q&A
    /replay <id>                              re-render a stored turn by its id
    /reset                                    clear in-session conversation history
    /quit  or  exit  or  Ctrl-C              exit
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import ollama

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_OLLAMA_BASE  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_AGENT_MODEL  = os.getenv("AGENT_MODEL", "gemma4-agent")


def _ollama_is_up(timeout: float = 1.5) -> bool:
    """Quick health probe against the Ollama HTTP API."""
    try:
        with urllib.request.urlopen(f"{_OLLAMA_BASE}/api/version", timeout=timeout):
            return True
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def _start_ollama() -> bool:
    """
    Launch the Ollama server in the background.

    On Windows the installer registers `ollama.exe` on PATH. We spawn it
    detached so it survives the CLI process. Returns True if the API
    becomes reachable within ~15s.
    """
    exe = shutil.which("ollama")
    if not exe:
        console.print(
            "[red]Ollama is not installed or not on PATH.[/red] "
            "Install it via [cyan].\\infra\\02_install_ollama.ps1[/cyan]."
        )
        return False

    console.print("[dim]Ollama not running — starting it now...[/dim]", end="\r")
    try:
        # CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS so closing this terminal
        # doesn't kill the server. Stdout/stderr discarded — Ollama logs to
        # %USERPROFILE%\.ollama\logs\server.log on its own.
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP   # type: ignore[attr-defined]
                | 0x00000008                          # DETACHED_PROCESS
            )
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as exc:
        console.print(f"\n[red]Failed to spawn Ollama: {exc}[/red]")
        return False

    # Poll until the API responds (max ~15s)
    for _ in range(30):
        if _ollama_is_up():
            console.print(" " * 60, end="\r")
            console.print("[dim]Ollama started.[/dim]")
            return True
        time.sleep(0.5)

    console.print("\n[red]Ollama did not become ready within 15s.[/red] "
                  "Check %USERPROFILE%\\.ollama\\logs\\server.log")
    return False


def _ensure_ollama_running() -> bool:
    """If the Ollama API isn't reachable, try to start it. Return True on success."""
    if _ollama_is_up():
        return True
    return _start_ollama()


def _warm_ollama():
    """Load the model into VRAM now so the first query has zero reload cost."""
    console.print("[dim]Loading model into GPU...[/dim]", end="\r")
    try:
        client = ollama.Client(host=_OLLAMA_BASE)
        # Empty-prompt generate with keep_alive pulls the model into VRAM
        # and keeps it there for the session lifetime.
        client.generate(model=_AGENT_MODEL, prompt="", keep_alive="120m")
        console.print(" " * 40, end="\r")
    except Exception as exc:
        console.print(f"\n[yellow]Warning: could not pre-load model ({exc}). "
                      "First query may be slow.[/yellow]")


def _warm_rag():
    """Pre-load embedding model and Chroma client so first query is fast."""
    console.print("[dim]Warming up embedding model...[/dim]", end="\r")
    from rag.retriever import _get_chroma_client, _get_embed_model
    _get_embed_model()
    _get_chroma_client()
    console.print(" " * 40, end="\r")  # clear the line


def _banner(platform: str):
    console.print(Panel(
        "[bold cyan]Cloud Platform Agent[/bold cyan]\n"
        "Gemma 4 26B · AMD Ryzen AI MAX+ 395 · Vulkan\n"
        f"Platform: [bold yellow]{platform}[/bold yellow]  "
        "[dim]| /platform <name>  /reset  /quit[/dim]",
        expand=False,
    ))


def _print_result(result: dict):
    platform = result.get("platform", "?")
    latency  = result.get("latency_ms", 0)
    tools    = result.get("tool_calls_made", [])
    sources  = result.get("rag_sources", [])

    # Main response
    console.print(Markdown(result["response"]))

    # Footer line
    meta = Text()
    meta.append(f"  platform={platform}", style="dim cyan")
    meta.append(f"  {latency}ms", style="dim")
    if tools:
        names = ", ".join(t["name"] for t in tools)
        meta.append(f"  tools=[{names}]", style="dim green")
    if sources:
        files = ", ".join(
            s["source"].replace("\\", "/").split("/")[-1]
            for s in sources[:3]
        )
        meta.append(f"  rag=[{files}]", style="dim magenta")
    console.print(meta)
    console.print()


def _run_cancellable(pipeline, query: str, override) -> dict | None:
    """
    Run pipeline.run() in a daemon thread so the main thread stays responsive
    to Ctrl-C. Returns the result, or None if the user cancelled.

    The thread keeps running in the background after cancellation (its HTTP
    request to Ollama will finish server-side) but we discard the result.
    """
    box: dict = {}

    def _worker():
        try:
            box["result"] = pipeline.run(query, platform_override=override)
        except Exception as exc:
            box["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    with console.status(
        "[bold yellow]thinking...[/bold yellow]  [dim](Ctrl-C to cancel)[/dim]"
    ):
        try:
            while t.is_alive():
                t.join(timeout=0.2)
        except KeyboardInterrupt:
            console.print("[yellow]Cancelled. (server request may finish in background.)[/yellow]")
            return None

    if "error" in box:
        raise box["error"]
    return box.get("result")


def _print_history_table(turns: list[dict]):
    if not turns:
        console.print("[dim]No history yet.[/dim]")
        return
    from rich.table import Table
    t = Table(show_header=True, header_style="bold cyan", expand=False)
    t.add_column("id", justify="right", style="dim")
    t.add_column("when", style="dim")
    t.add_column("platform", style="cyan")
    t.add_column("ms", justify="right", style="dim")
    t.add_column("query", overflow="fold")
    for r in turns:
        when = (r.get("ts") or "").replace("T", " ")
        q    = (r.get("query") or "").strip().replace("\n", " ")
        if len(q) > 80:
            q = q[:77] + "..."
        t.add_row(
            str(r.get("id", "")),
            when,
            str(r.get("platform", "")),
            str(r.get("latency_ms", 0)),
            q,
        )
    console.print(t)


def main():
    parser = argparse.ArgumentParser(description="Cloud Platform Agent CLI")
    parser.add_argument(
        "--platform",
        choices=["auto", "databricks", "snowflake", "aws"],
        default="auto",
        help="Lock to a platform or let the router decide (default: auto)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Disable persistent Q&A history for this session",
    )
    args = parser.parse_args()
    current_platform = args.platform

    if not _ensure_ollama_running():
        console.print("[red]Cannot continue without Ollama. Exiting.[/red]")
        sys.exit(1)

    _warm_rag()
    _warm_ollama()

    from orchestrator.pipeline import AgentPipeline
    pipeline = AgentPipeline()

    # Persistent history (SQLite + daily markdown)
    history_enabled = not args.no_history and os.environ.get("DSA_HISTORY", "1") != "0"
    from orchestrator.history import History, format_full_markdown
    history = History(enabled=history_enabled)
    if history_enabled:
        console.print(
            f"[dim]History: {history.db_path} "
            f"({history.count()} turns recorded)[/dim]"
        )

    _banner(current_platform)

    # Track the most recent turn so /save and /copy can act on it
    last_query: str | None = None
    last_result: dict | None = None

    while True:
        try:
            user_input = console.input("[bold green]you>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            sys.exit(0)

        if not user_input:
            continue

        # --- built-in commands ---
        if user_input.lower() in ("/quit", "exit", "quit"):
            console.print("[dim]Bye.[/dim]")
            sys.exit(0)

        if user_input.lower() == "/reset":
            pipeline.reset()
            console.print("[dim]Session history cleared.[/dim]")
            continue

        if user_input.lower() == "/save" or user_input.lower().startswith("/save "):
            if last_result is None:
                console.print("[yellow]Nothing to save yet — ask a question first.[/yellow]")
                continue
            from orchestrator.exporter import save_turn
            parts = user_input.split(maxsplit=1)
            fname = parts[1].strip() if len(parts) == 2 else None
            try:
                path = save_turn(last_query or "", last_result, filename=fname)
                console.print(f"[green]Saved:[/green] {path}")
            except Exception as exc:
                console.print(f"[red]Save failed: {exc}[/red]")
            continue

        if user_input.lower() == "/copy":
            if last_result is None:
                console.print("[yellow]Nothing to copy yet — ask a question first.[/yellow]")
                continue
            from orchestrator.exporter import copy_to_clipboard
            text = last_result.get("response", "") or ""
            if copy_to_clipboard(text):
                console.print(f"[green]Copied {len(text)} chars to clipboard.[/green]")
            else:
                console.print("[red]Clipboard copy failed — no clipboard utility found.[/red]")
            continue

        if user_input.lower() == "/history" or user_input.lower().startswith("/history "):
            parts = user_input.split(maxsplit=1)
            try:
                n = int(parts[1]) if len(parts) == 2 else 10
            except ValueError:
                console.print("[red]Usage: /history [N][/red]")
                continue
            _print_history_table(history.recent(limit=n))
            continue

        if user_input.lower().startswith("/search "):
            keyword = user_input.split(maxsplit=1)[1].strip()
            if not keyword:
                console.print("[red]Usage: /search <keyword>[/red]")
                continue
            matches = history.search(keyword, limit=20)
            if not matches:
                console.print(f"[yellow]No matches for '{keyword}'.[/yellow]")
            else:
                console.print(f"[dim]{len(matches)} match(es) for '{keyword}':[/dim]")
                _print_history_table(matches)
            continue

        if user_input.lower().startswith("/replay "):
            parts = user_input.split(maxsplit=1)
            try:
                turn_id = int(parts[1].strip())
            except (IndexError, ValueError):
                console.print("[red]Usage: /replay <id>[/red]")
                continue
            turn = history.get(turn_id)
            if not turn:
                console.print(f"[yellow]No turn with id {turn_id}.[/yellow]")
                continue
            console.print(f"[dim]Replaying turn #{turn_id} from {turn['ts']}[/dim]")
            console.print(f"[bold green]Q:[/bold green] {turn['query']}")
            console.print()
            from orchestrator.history import turn_to_result
            _print_result(turn_to_result(turn) | {"platform": turn["platform"]})
            # Make /save and /copy operate on the replayed turn
            last_query  = turn["query"]
            last_result = turn_to_result(turn) | {"platform": turn["platform"]}
            continue

        if user_input.lower().startswith("/platform "):
            chosen = user_input.split(maxsplit=1)[1].strip().lower()
            if chosen in ("auto", "databricks", "snowflake", "aws"):
                current_platform = chosen
                console.print(f"[dim]Platform set to [bold]{current_platform}[/bold][/dim]")
            else:
                console.print("[red]Unknown platform. Choose: auto databricks snowflake aws[/red]")
            continue

        # --- agent query ---
        override = None if current_platform == "auto" else current_platform
        try:
            result = _run_cancellable(pipeline, user_input, override)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            continue
        if result is None:
            # User pressed Ctrl-C during thinking; loop back to prompt
            continue

        last_query = user_input
        last_result = result
        _print_result(result)

        # Persist to history (SQLite + daily markdown). Best-effort.
        try:
            history.append(user_input, result)
        except Exception as exc:
            console.print(f"[dim red]History append failed: {exc}[/dim red]")


if __name__ == "__main__":
    main()
