"""
Base agent: tool-calling loop with RAG context injection.
"""
from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod

import ollama
from tenacity import retry, stop_after_attempt, wait_exponential

from rag.retriever import retrieve

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_ITERATIONS = 8


class BaseAgent(ABC):
    platform: str
    tool_schemas: list
    tool_executors: dict
    system_template: str   # must contain {rag_context}

    def __init__(self, model: str):
        self.model = model
        self.client = ollama.Client(host=OLLAMA_BASE)
        self.register_tools()

    @abstractmethod
    def register_tools(self):
        pass

    def run(self, query: str, history: list | None = None) -> dict:
        t0 = time.time()
        tool_log: list[dict] = []

        rag_results = retrieve(self.platform, query)
        rag_context = self._fmt_rag(rag_results)
        rag_sources = [{"source": r["source"], "score": r["score"]} for r in rag_results]

        messages = (
            [{"role": "system",
              "content": self.system_template.format(rag_context=rag_context)}]
            + (history or [])
            + [{"role": "user", "content": query}]
        )

        for _ in range(MAX_ITERATIONS):
            resp = self._llm(messages)
            msg = resp.message

            if not getattr(msg, "tool_calls", None):
                return {
                    "response":        msg.content or "",
                    "tool_calls_made": tool_log,
                    "rag_sources":     rag_sources,
                    "latency_ms":      int((time.time() - t0) * 1000),
                }

            messages.append({
                "role":       "assistant",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                name = tc.function.name
                args = tc.function.arguments or {}
                result = self._run_tool(name, args)
                tool_log.append({"name": name, "args": args, "result": result})
                messages.append({
                    "role":      "tool",
                    "tool_name": name,
                    "content":   json.dumps(result, default=str),
                })

        return {
            "response":        "Max iterations reached. See tool_calls_made for partial results.",
            "tool_calls_made": tool_log,
            "rag_sources":     rag_sources,
            "latency_ms":      int((time.time() - t0) * 1000),
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _llm(self, messages):
        return self.client.chat(
            model=self.model,
            messages=messages,
            tools=self.tool_schemas,
            options={"temperature": 0.1, "num_predict": 2048},
            keep_alive="60m",   # pin model in VRAM between queries
        )

    def _run_tool(self, name: str, args: dict) -> dict:
        fn = self.tool_executors.get(name)
        if not fn:
            return {"error": f"No executor registered for tool: {name}"}
        try:
            return fn(**args)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "tool": name}

    def _fmt_rag(self, results: list) -> str:
        if not results:
            return "No relevant documentation retrieved."
        return "\n".join(
            f"[Source: {r['source']} | Score: {r['score']:.2f}]\n{r['content'].strip()}\n"
            for r in results[:5]
        )
