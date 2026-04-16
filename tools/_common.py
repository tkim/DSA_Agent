"""
Shared helpers for tool executors.

Pattern:
- Env vars missing -> mock response with "_mock": True
- Exception -> {"error": str(e), "tool": tool_name}
- Live SDK calls wrapped in ThreadPoolExecutor with 15s timeout
"""
from __future__ import annotations

import concurrent.futures
import os
from functools import wraps
from typing import Callable, Iterable

_TIMEOUT_S = 15


def env_ready(*names: str) -> bool:
    """True when all env vars in `names` are non-empty."""
    return all(os.getenv(n) for n in names)


def run_with_timeout(fn: Callable, *args, **kwargs):
    """Execute `fn` in a worker thread with a 15s timeout."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, *args, **kwargs)
        return future.result(timeout=_TIMEOUT_S)


def tool_wrapper(name: str):
    """Decorator: catch all exceptions and return error dict shape."""
    def deco(fn: Callable):
        @wraps(fn)
        def inner(**kwargs):
            try:
                return fn(**kwargs)
            except concurrent.futures.TimeoutError:
                return {"error": f"Tool {name} timed out after {_TIMEOUT_S}s", "tool": name}
            except Exception as exc:  # noqa: BLE001
                return {"error": str(exc), "tool": name}
        return inner
    return deco


def required(kwargs: dict, names: Iterable[str]) -> dict | None:
    """Return an error dict if any required kwarg is missing; else None."""
    missing = [n for n in names if kwargs.get(n) in (None, "")]
    if missing:
        return {"error": f"Missing required argument(s): {', '.join(missing)}"}
    return None
