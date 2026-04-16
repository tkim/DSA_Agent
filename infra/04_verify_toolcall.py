#!/usr/bin/env python3
"""
Gemma 4 tool-calling gate test - Windows / Vulkan / Ollama.
Uses only stdlib (no requests dependency). Run after 03_pull_model.ps1.
Must pass 3/3 before writing any agent code.
"""
import json, sys, time, urllib.request, urllib.error

BASE  = "http://localhost:11434"
MODEL = "gemma4-agent"
OK    = "\033[92m[PASS]\033[0m"
FAIL  = "\033[91m[FAIL]\033[0m"

CLUSTER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_cluster_status",
        "description": "Get the current state of a Databricks cluster",
        "parameters": {
            "type": "object",
            "properties": {
                "cluster_id": {
                    "type": "string",
                    "description": "The Databricks cluster ID"
                }
            },
            "required": ["cluster_id"]
        }
    }
}


def post(messages: list, tools: list = None) -> tuple[dict, int]:
    payload = {"model": MODEL, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        f"{BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        result = json.loads(r.read())
    return result, int((time.time() - t0) * 1000)


def test_single_tool_call() -> bool:
    msgs = [{"role": "user", "content": "What is the status of cluster 0123-abc456?"}]
    try:
        data, ms = post(msgs, tools=[CLUSTER_TOOL])
        calls = data.get("message", {}).get("tool_calls", [])
        if calls and calls[0]["function"]["name"] == "get_cluster_status":
            args = calls[0]["function"]["arguments"]
            if "cluster_id" in args:
                print(f"{OK} Single tool call ({ms}ms) - args: {args}")
                return True
        print(f"{FAIL} No valid tool call returned. Message: {data.get('message', {})}")
    except Exception as e:
        print(f"{FAIL} Request error: {e}")
    return False


def test_multi_turn() -> bool:
    msgs = [
        {"role": "user", "content": "Check cluster 0123-abc456."},
        {
            "role": "assistant",
            "tool_calls": [{
                "function": {
                    "name": "get_cluster_status",
                    "arguments": {"cluster_id": "0123-abc456"}
                }
            }]
        },
        {
            "role": "tool",
            "tool_name": "get_cluster_status",
            "content": json.dumps({
                "state": "RUNNING", "num_workers": 4,
                "cluster_id": "0123-abc456", "driver": "Standard_DS3_v2"
            })
        }
    ]
    try:
        data, ms = post(msgs)
        content = data.get("message", {}).get("content", "")
        if "RUNNING" in content or "running" in content.lower():
            print(f"{OK} Multi-turn tool result injection ({ms}ms)")
            return True
        print(f"{FAIL} Expected 'RUNNING' in response. Got: {content[:200]}")
    except Exception as e:
        print(f"{FAIL} Request error: {e}")
    return False


def test_no_hallucination() -> bool:
    msgs = [{"role": "user", "content": "What is 15 multiplied by 7?"}]
    try:
        data, ms = post(msgs)   # no tools registered
        msg = data.get("message", {})
        if msg.get("tool_calls"):
            print(f"{FAIL} Phantom tool calls: {msg['tool_calls']}")
            return False
        print(f"{OK} No hallucinated tool calls ({ms}ms)")
        return True
    except Exception as e:
        print(f"{FAIL} Request error: {e}")
        return False


if __name__ == "__main__":
    print(f"\n=== Gemma 4 Tool-Call Gate Test (Windows / Vulkan) ===")
    print(f"    Model: {MODEL}\n")

    results = [
        test_single_tool_call(),
        test_multi_turn(),
        test_no_hallucination(),
    ]
    passed = sum(results)
    print(f"\n{'-' * 52}")
    print(f"  Result: {passed}/{len(results)} passed\n")

    if passed < len(results):
        print("Windows troubleshooting checklist:")
        print("  1. ollama --version         # must be >= 0.20.2")
        print("  2. $env:OLLAMA_VULKAN       # must print '1' (new terminal!)")
        print("  3. ollama list              # gemma4-agent must appear")
        print("  4. ollama ps               # GPU column must be nonzero after warm")
        print("  5. AMD Adrenalin VGM       # set Custom 96 GB and rebooted?")
        print("  6. Ollama restarted        # after setting env vars?")
        print("  7. Check logs:             # %USERPROFILE%\\.ollama\\logs\\server.log")
        sys.exit(1)

    print("  All checks passed. Proceed to Phase 1.\n")
