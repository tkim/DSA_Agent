"""
Cloud Platform Agent — interactive CLI.

Usage:
    python cli.py                  # auto-route every query
    python cli.py --platform aws   # lock to one platform

Commands (type during chat):
    /platform auto|databricks|snowflake|aws   switch platform
    /reset                                    clear conversation history
    /quit  or  exit  or  Ctrl-C              exit
"""
from __future__ import annotations

import argparse
import os
import sys

import ollama

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_OLLAMA_BASE  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_AGENT_MODEL  = os.getenv("AGENT_MODEL", "gemma4-agent")


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


def main():
    parser = argparse.ArgumentParser(description="Cloud Platform Agent CLI")
    parser.add_argument(
        "--platform",
        choices=["auto", "databricks", "snowflake", "aws"],
        default="auto",
        help="Lock to a platform or let the router decide (default: auto)",
    )
    args = parser.parse_args()
    current_platform = args.platform

    _warm_rag()
    _warm_ollama()

    from orchestrator.pipeline import AgentPipeline
    pipeline = AgentPipeline()

    _banner(current_platform)

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
        with console.status("[bold yellow]thinking...[/bold yellow]"):
            try:
                result = pipeline.run(user_input, platform_override=override)
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
                continue

        _print_result(result)


if __name__ == "__main__":
    main()
