"""
Evaluation harness.

Runs all queries in eval/queries/*.json through AgentPipeline and scores:
- tool selection accuracy (expected_tool matches first tool called)
- required-arg hit rate
- routing accuracy
- p50 / p95 latency

CLI:
    python -m eval.evaluate --mock        # all queries, mock mode (no live creds)
    python -m eval.evaluate --platform databricks
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agents.router import Router
from orchestrator.pipeline import AgentPipeline

PLATFORMS = ("databricks", "snowflake", "aws")


def _load(platform: str) -> list[dict]:
    path = Path("eval") / "queries" / f"{platform}_queries.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _score_query(expected: dict, result: dict, router_platform: str) -> dict:
    tool_calls = result.get("tool_calls_made", [])
    first_tool = tool_calls[0]["name"] if tool_calls else None
    first_args = tool_calls[0]["args"] if tool_calls else {}

    et = expected.get("expected_tool")
    tool_ok = (et is None and not tool_calls) or (et is not None and first_tool == et)

    req = expected.get("required_args", []) or []
    req_ok = all(k in first_args for k in req) if req else True

    exp_vals = expected.get("expected_arg_values", {}) or {}
    val_ok = all(str(first_args.get(k)) == str(v) for k, v in exp_vals.items()) if exp_vals else True

    rag_ok = True
    if expected.get("type") == "rag_only":
        kw = (expected.get("expected_rag_keyword") or "").lower()
        body = (result.get("response") or "").lower()
        rag_ok = kw in body if kw else True

    route_ok = router_platform == result.get("platform")

    return {
        "id": expected["id"],
        "type": expected["type"],
        "tool_ok": tool_ok,
        "req_ok": req_ok,
        "val_ok": val_ok,
        "rag_ok": rag_ok,
        "route_ok": route_ok,
        "latency_ms": result.get("latency_ms", 0),
    }


def run_platform(platform: str) -> list[dict]:
    pipeline = AgentPipeline.get()
    router = Router()
    console = Console()
    queries = _load(platform)
    console.print(f"\n[bold cyan]== {platform} ({len(queries)} queries) ==[/]")

    scored: list[dict] = []
    for q in queries:
        router_platform = router.route(q["query"])
        t0 = time.time()
        result = pipeline.run(q["query"], platform_override=platform)
        dt = int((time.time() - t0) * 1000)
        if "latency_ms" not in result:
            result["latency_ms"] = dt
        s = _score_query(q, result, router_platform)
        scored.append(s)
        pipeline.reset()

        mark = "ok " if s["tool_ok"] and s["req_ok"] and s["val_ok"] and s["rag_ok"] else "X  "
        console.print(f"  {mark}{q['id']} [{q['type']}] tool={s['tool_ok']} req={s['req_ok']} "
                      f"val={s['val_ok']} rag={s['rag_ok']} route={s['route_ok']} "
                      f"{s['latency_ms']}ms")

    return scored


def summarize(platform: str, scored: list[dict]) -> dict:
    n = len(scored)
    lat = [s["latency_ms"] for s in scored]

    def pct(key):
        return round(100 * sum(1 for s in scored if s[key]) / n, 1) if n else 0.0

    summary = {
        "platform": platform,
        "n": n,
        "tool_selection_accuracy": pct("tool_ok"),
        "required_arg_hit_rate": pct("req_ok"),
        "arg_value_hit_rate": pct("val_ok"),
        "rag_keyword_hit_rate": pct("rag_ok"),
        "routing_accuracy": pct("route_ok"),
        "p50_latency_ms": int(statistics.median(lat)) if lat else 0,
        "p95_latency_ms": int(sorted(lat)[int(0.95 * (n - 1))]) if n else 0,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=PLATFORMS)
    parser.add_argument("--mock", action="store_true", help="Informational only; mock is auto when env vars are absent")
    args = parser.parse_args()

    console = Console()
    targets = (args.platform,) if args.platform else PLATFORMS

    all_scores: dict[str, list[dict]] = {}
    summaries: list[dict] = []
    for p in targets:
        scored = run_platform(p)
        all_scores[p] = scored
        summaries.append(summarize(p, scored))

    table = Table(title="Evaluation summary")
    cols = ["platform", "n", "tool_selection_accuracy", "required_arg_hit_rate",
            "arg_value_hit_rate", "rag_keyword_hit_rate", "routing_accuracy",
            "p50_latency_ms", "p95_latency_ms"]
    for c in cols:
        table.add_column(c)
    for s in summaries:
        table.add_row(*[str(s[c]) for c in cols])
    console.print(table)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path("eval") / f"results_{ts}.json"
    out.write_text(json.dumps({"summaries": summaries, "scores": all_scores}, indent=2), encoding="utf-8")
    console.print(f"[green]Results written to {out}[/]")


if __name__ == "__main__":
    main()
