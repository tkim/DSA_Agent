# Cloud Platform Agent System — Claude Code Project Specification
## Gemma 4 26B A4B · Ollama · Windows 11 Native · AMD Ryzen AI MAX+ 395
## Databricks / Snowflake / AWS

---

## Hardware profile and Windows constraints (read before anything else)

| Component | Spec | Windows implication |
|---|---|---|
| CPU | Ryzen AI MAX+ 395, 16 × Zen 5, up to 5.1 GHz | Fast tokenizer; Python toolchain runs here |
| GPU | Radeon 8060S, 40 RDNA 3.5 CUs, gfx1151 | **Vulkan only** on Windows — no ROCm |
| NPU | XDNA 2, 50 TOPS | Windows Studio Effects only; not used by Ollama |
| Memory | 128 GB LPDDR5X-8000 unified | Up to **96 GB VGM** via AMD Adrenalin on Windows |
| Bandwidth | ~256 GB/s CPU+GPU shared | No PCIe bottleneck regardless of OS |

**The single most important Windows fact:**
ROCm does not support AMD integrated GPUs (Ryzen AI series) on Windows.
The only GPU acceleration path for the Radeon 8060S on Windows is Vulkan.
Set `OLLAMA_VULKAN=1` as a persistent system environment variable. That is the entire
GPU setup — no HSA overrides, no ROCm forks, no extra drivers beyond Adrenalin.

**VRAM on Windows:** AMD Variable Graphics Memory (VGM) caps at 96 GB on Windows
(Linux GTT reaches ~120 GB). Gemma 4 26B A4B at Q4_K_M = ~17 GB.
All three specialist agents fit simultaneously: 3 × 17 GB = 51 GB used, 45 GB free.

**No WSL2.** Every command in this spec is native Windows PowerShell.

---

## Repository layout

```
cloud-agents\
├── CLAUDE.md                          ← this file
├── pyproject.toml
├── .env.example
├── .env                               ← copy from .env.example; fill secrets
│
├── infra\
│   ├── 00_check_hardware.ps1          ← run first; verify GPU, VGM, Ollama
│   ├── 01_setup_vgm.md                ← AMD Adrenalin VGM guide (manual UI steps)
│   ├── 02_install_ollama.ps1          ← install + configure Vulkan env vars
│   ├── 03_pull_model.ps1              ← pull gemma4:26b; create Modelfile
│   ├── 04_verify_toolcall.py          ← gate test: MUST show 3/3 PASS
│   ├── 05_benchmark_inference.ps1     ← baseline tok/s
│   └── modelfiles\
│       └── Gemma4Agent.modelfile
│
├── agents\
│   ├── __init__.py
│   ├── base_agent.py
│   ├── router.py
│   ├── databricks_agent.py
│   ├── snowflake_agent.py
│   └── aws_agent.py
│
├── tools\
│   ├── __init__.py
│   ├── databricks_tools.py
│   ├── snowflake_tools.py
│   └── aws_tools.py
│
├── rag\
│   ├── __init__.py
│   ├── ingestor.py
│   ├── retriever.py
│   ├── fetch_docs.ps1
│   └── chroma_db\                     ← gitignored; populated at runtime
│
├── orchestrator\
│   ├── __init__.py
│   ├── session.py
│   └── pipeline.py
│
├── eval\
│   ├── queries\
│   │   ├── databricks_queries.json
│   │   ├── snowflake_queries.json
│   │   └── aws_queries.json
│   └── evaluate.py
│
├── ui\
│   └── chat.py
│
└── tests\
    ├── test_tools_mock.py
    ├── test_agents_mock.py
    └── test_router.py
```

---

## Phase 0 — Windows environment setup (mandatory gate)

### `infra\00_check_hardware.ps1`

Run this first. Do not proceed until all checks are green.

```powershell
#Requires -Version 5.1
Write-Host "=== Ryzen AI MAX+ 395 — Windows Hardware Check ===" -ForegroundColor Cyan

Write-Host "`n--- CPU ---"
(Get-WmiObject Win32_Processor).Name

Write-Host "`n--- GPU ---"
Get-WmiObject Win32_VideoController |
    Select-Object Name, AdapterRAM, DriverVersion |
    Format-Table -AutoSize

Write-Host "`n--- Total RAM ---"
$gb = (Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory / 1GB
"Total physical memory: {0:N1} GB" -f $gb

Write-Host "`n--- GPU VRAM (VGM) ---"
$vram = (Get-WmiObject Win32_VideoController |
    Where-Object { $_.Name -match "AMD|Radeon" }).AdapterRAM
if ($vram) {
    "Reported GPU VRAM: {0:N1} GB (target: ~96 GB after Adrenalin VGM setup)" -f ($vram / 1GB)
} else {
    "Cannot read GPU VRAM via WMI — check AMD Adrenalin app directly"
}

Write-Host "`n--- AMD Driver ---"
$drv = (Get-WmiObject Win32_VideoController |
    Where-Object { $_.Name -match "AMD|Radeon" }).DriverVersion
"Driver: $drv  (need Adrenalin 25.8.1 WHQL or later)"

Write-Host "`n--- Ollama ---"
try {
    $ver = (& ollama --version 2>&1) -replace "ollama version ",""
    "Ollama: $ver  (need >= 0.20.2 for Gemma 4 tool calling)"
} catch { "Ollama not installed — run 02_install_ollama.ps1" }

Write-Host "`n--- Vulkan env var ---"
$sys  = [Environment]::GetEnvironmentVariable("OLLAMA_VULKAN","Machine")
$user = [Environment]::GetEnvironmentVariable("OLLAMA_VULKAN","User")
if ($sys -eq "1") {
    Write-Host "OLLAMA_VULKAN=1 [System] — CORRECT" -ForegroundColor Green
} elseif ($user -eq "1") {
    Write-Host "OLLAMA_VULKAN=1 [User] — OK (system-level preferred)" -ForegroundColor Yellow
} else {
    Write-Host "OLLAMA_VULKAN not set — GPU will NOT be used!" -ForegroundColor Red
    Write-Host "Run 02_install_ollama.ps1 as Administrator"
}

Write-Host "`n--- Flash Attention env var ---"
$fa = [Environment]::GetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","Machine")
if ($fa -eq "1") {
    Write-Host "OLLAMA_FLASH_ATTENTION=1 [System] — CORRECT" -ForegroundColor Green
} else {
    Write-Host "OLLAMA_FLASH_ATTENTION not set — run 02_install_ollama.ps1" -ForegroundColor Yellow
}
```

---

### `infra\01_setup_vgm.md` — AMD Adrenalin VGM configuration (manual)

**Complete this before installing Ollama. Requires a reboot.**

GPU memory on Windows is set through AMD's Adrenalin driver UI — there is no command-line
equivalent on Windows. By default the GPU memory allocation is very conservative (4–8 GB),
which causes Ollama and llama.cpp to route 26B models to the CPU.

**Steps:**

1. Download AMD Software: Adrenalin Edition 25.8.1 WHQL or later
   URL: https://www.amd.com/en/support/downloads/drivers.html
   Category: Graphics → Integrated Graphics → Radeon 8060S

2. Run the installer. Reboot if prompted.

3. Open **AMD Software: Adrenalin Edition**

4. Go to: **Performance** → **Tuning** → **System** → **Variable Graphics Memory**

5. Change the dropdown to **Custom**

6. Enter **96** (GB)
   Rationale: 96 GB GPU + 32 GB system RAM is the recommended split for LLM use.
   32 GB is sufficient for Windows 11, Chrome, VS Code, and the full Python agent stack.
   Do not set to 128 GB — Windows needs at least 16–32 GB system RAM to operate.

7. Click **Apply**, then **Restart Now**

8. After reboot, re-run `infra\00_check_hardware.ps1` and confirm GPU VRAM ~96 GB

**Verification in Ollama after model load:**
```powershell
ollama ps
# The GPU column must show ~17 GB for gemma4-agent (not CPU, not 0)
```

---

### `infra\02_install_ollama.ps1`

Run as **Administrator** (right-click PowerShell → Run as Administrator).

```powershell
#Requires -RunAsAdministrator

# ── Install Ollama ─────────────────────────────────────────────────────────────
Write-Host "Installing Ollama for Windows..." -ForegroundColor Cyan
winget install Ollama.Ollama `
    --silent `
    --accept-package-agreements `
    --accept-source-agreements

# Refresh PATH in this session
$machinePath = [Environment]::GetEnvironmentVariable("PATH","Machine")
$userPath    = [Environment]::GetEnvironmentVariable("PATH","User")
$env:PATH    = "$machinePath;$userPath"

# ── Version gate ───────────────────────────────────────────────────────────────
$rawVer  = (& ollama --version 2>&1) -replace "ollama version ",""
$semVer  = [Version]($rawVer -replace "^(\d+\.\d+\.\d+).*",'$1')
$minVer  = [Version]"0.20.2"
Write-Host "Ollama version: $rawVer"
if ($semVer -lt $minVer) {
    Write-Error "Version $rawVer < 0.20.2. Gemma 4 tool calling will fail."
    Write-Host  "Update: winget upgrade Ollama.Ollama"
    exit 1
}
Write-Host "Version OK" -ForegroundColor Green

# ── Set system-level environment variables ─────────────────────────────────────
# These persist across reboots and apply to all users.
# IMPORTANT: Ollama must be restarted after setting these (tray → Quit → reopen).
$envVars = [ordered]@{
    OLLAMA_VULKAN          = "1"      # Mandatory: use Vulkan GPU (Radeon 8060S)
    OLLAMA_FLASH_ATTENTION = "1"      # Efficient long-context attention
    OLLAMA_KEEP_ALIVE      = "60m"    # Keep model warm (96 GB VGM = no pressure)
    OLLAMA_NUM_GPU         = "1"      # One GPU (iGPU)
    OLLAMA_CONTEXT_LENGTH  = "32768"  # Start at 32K; bump to 65536 once stable
}

Write-Host "`nSetting system environment variables:" -ForegroundColor Cyan
foreach ($key in $envVars.Keys) {
    [Environment]::SetEnvironmentVariable($key, $envVars[$key], "Machine")
    # Also apply to current session
    [Environment]::SetEnvironmentVariable($key, $envVars[$key], "Process")
    Write-Host "  $key = $($envVars[$key])"
}

# ── Restart Ollama tray app to pick up new vars ────────────────────────────────
Write-Host "`nRestarting Ollama..." -ForegroundColor Cyan
Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 4

# ── Verify API ─────────────────────────────────────────────────────────────────
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -Method GET
    Write-Host "Ollama API OK — version: $($resp.version)" -ForegroundColor Green
} catch {
    Write-Warning "Ollama API not reachable. Try opening Ollama from Start Menu."
}

Write-Host @"

Next steps:
  1. Open a NEW PowerShell window (env vars only take effect in new sessions)
  2. Verify: `$env:OLLAMA_VULKAN   should print  1
  3. Run:    .\infra\03_pull_model.ps1
"@ -ForegroundColor Yellow
```

---

### `infra\03_pull_model.ps1`

```powershell
# Pull Gemma 4 26B and register the gemma4-agent Modelfile.
# Requires OLLAMA_VULKAN=1 to already be set (run in new terminal after 02_install_ollama.ps1).

Write-Host "Verifying Vulkan is active..." -ForegroundColor Cyan
if ($env:OLLAMA_VULKAN -ne "1") {
    Write-Error "OLLAMA_VULKAN is not '1' in this session. Open a new terminal and retry."
    exit 1
}

Write-Host "Pulling gemma4:26b (~17 GB)..." -ForegroundColor Cyan
ollama pull gemma4:26b

# Create Modelfile
$dir = "infra\modelfiles"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

@'
FROM gemma4:26b

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER top_k 20
PARAMETER repeat_penalty 1.05
PARAMETER num_ctx 32768
PARAMETER num_predict 4096

SYSTEM """
You are a precise cloud infrastructure specialist with live tool access.

Rules:
1. When a tool can answer the request, call it immediately. Do not describe what you would do.
2. Think step by step inside <think> tags before choosing which tool to call.
3. After each tool result, incorporate it before deciding the next action.
4. If a tool returns an error, report the exact error message to the user.
5. Never fabricate cluster IDs, table names, policy ARNs, SQL results, or metric values.
6. Return technically precise answers and cite tool output directly.
"""
'@ | Set-Content -Path "$dir\Gemma4Agent.modelfile" -Encoding UTF8

Write-Host "Creating gemma4-agent..." -ForegroundColor Cyan
ollama create gemma4-agent -f "$dir\Gemma4Agent.modelfile"

Write-Host "Warming model into GPU memory (keep_alive=60m)..."
$body = '{"model":"gemma4-agent","prompt":"","keep_alive":"60m"}'
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/generate" `
        -Method POST -Body $body -ContentType "application/json" | Out-Null
    Write-Host "Model warm." -ForegroundColor Green
} catch {
    Write-Warning "Warm-up call failed: $_"
}

Write-Host "`nGPU placement check:"
ollama ps
Write-Host "(GPU column should show ~17 GB for gemma4-agent, not CPU or 0)"
```

---

### `infra\04_verify_toolcall.py` — gate test (MUST show 3/3 PASS)

```python
#!/usr/bin/env python3
"""
Gemma 4 tool-calling gate test — Windows / Vulkan / Ollama.
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
                print(f"{OK} Single tool call ({ms}ms) — args: {args}")
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
    print(f"\n{'─' * 52}")
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
```

---

### `infra\05_benchmark_inference.ps1`

```powershell
# Baseline tok/s on Windows Vulkan. Expected for gemma4:26b Q4_K_M:
#   Token generation: ~15-25 tok/s
#   Prompt processing: ~150-350 tok/s
# (Slightly lower than Linux due to Windows Vulkan driver overhead)

Write-Host "=== Inference Benchmark (Windows / Vulkan) ===" -ForegroundColor Cyan

$body = @{
    model  = "gemma4-agent"
    prompt = "Explain Delta Lake ACID transactions and time travel in exactly 5 sentences."
    stream = $false
} | ConvertTo-Json

Write-Host "Sending benchmark prompt..."
$t0   = Get-Date
$resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" `
        -Method POST -Body $body -ContentType "application/json"
$secs = ((Get-Date) - $t0).TotalSeconds

Write-Host "`nPreview: $($resp.response.Substring(0, [Math]::Min(180,$resp.response.Length)))..."
Write-Host ""
"Elapsed total:    {0:N1}s"   -f $secs
"Eval tokens:      {0}"       -f $resp.eval_count
if ($resp.eval_duration -gt 0) {
    "Token gen speed:  {0:N1} tok/s" -f ($resp.eval_count / ($resp.eval_duration / 1e9))
}
if ($resp.prompt_eval_duration -gt 0) {
    "Prompt proc:      {0:N1} tok/s" -f ($resp.prompt_eval_count / ($resp.prompt_eval_duration / 1e9))
}

Write-Host "`nMonitor GPU usage:" -ForegroundColor Yellow
Write-Host "  Task Manager > Performance > GPU"
Write-Host "  AMD Software > Performance > Metrics (enable GPU clock + memory utilization)"
```

---

## Phase 1 — Project scaffolding

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "cloud-agents"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "ollama>=0.4.0",
    "chromadb>=0.5.20",
    "sentence-transformers>=3.1.0",
    "langchain>=0.3.0",
    "langchain-community>=0.3.0",
    "langchain-ollama>=0.2.0",
    "databricks-sdk>=0.25.0",
    "snowflake-connector-python>=3.8.0",
    "boto3>=1.35.0",
    "gradio>=5.0.0",
    "pydantic>=2.7.0",
    "python-dotenv>=1.0.0",
    "rich>=13.7.0",
    "tenacity>=8.3.0",
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.5.0",
]
```

### Python virtual environment (Windows)

Use `uv` — fastest dependency resolver, native Windows support:

```powershell
# Install uv (one-time)
winget install astral-sh.uv

# Create venv and install project
uv venv .venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -e .

# Verify
python -c "import ollama, chromadb, gradio; print('All deps OK')"
```

Alternatively with Miniconda:
```powershell
conda create -n cloud-agents python=3.11 -y
conda activate cloud-agents
pip install -e .
```

### `.env.example`

```ini
# Inference
OLLAMA_BASE_URL=http://localhost:11434
AGENT_MODEL=gemma4-agent
ROUTER_MODEL=gemma4-agent

# RAG
CHROMA_PERSIST_DIR=.\rag\chroma_db
EMBED_MODEL=all-MiniLM-L6-v2
RAG_TOP_K=5
RAG_CHUNK_SIZE=512
RAG_CHUNK_OVERLAP=64

# Databricks (leave blank for mock mode)
DATABRICKS_HOST=https://your-workspace.azuredatabricks.net
DATABRICKS_TOKEN=dapi...

# Snowflake
SNOWFLAKE_ACCOUNT=your_account
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=your_db
SNOWFLAKE_SCHEMA=PUBLIC

# AWS
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

Load in Python with:
```python
from dotenv import load_dotenv
load_dotenv()  # reads .env from project root
```

### `.gitignore`

```
.venv\
__pycache__\
*.pyc
.env
rag\chroma_db\
*.gguf
infra\modelfiles\*.modelfile
```

---

## Phase 2 — RAG pipeline

### `rag\fetch_docs.ps1`

```powershell
$dirs = "rag\docs\databricks","rag\docs\snowflake","rag\docs\aws"
$dirs | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

Write-Host "Fetching Databricks docs..." -ForegroundColor Cyan
@(
    @{ Uri="https://raw.githubusercontent.com/delta-io/delta/master/docs/source/delta-intro.md"
       Out="rag\docs\databricks\delta_intro.md" },
    @{ Uri="https://raw.githubusercontent.com/delta-io/delta/master/docs/source/best-practices.md"
       Out="rag\docs\databricks\delta_best_practices.md" }
) | ForEach-Object {
    try   { Invoke-WebRequest -Uri $_.Uri -OutFile $_.Out -EA Stop; Write-Host "  OK $($_.Out)" }
    catch { Write-Warning "  SKIP $($_.Out): $($_.Exception.Message)" }
}

Write-Host "Generating AWS Boto3 reference docs..." -ForegroundColor Cyan
python -c "
import boto3, pydoc, os
os.makedirs('rag/docs/aws', exist_ok=True)
for svc in ['s3','glue','bedrock-runtime','iam','lambda','ec2']:
    try:
        c = boto3.client(svc, region_name='us-east-1')
        doc = pydoc.render_doc(type(c), renderer=pydoc.plaintext)
        path = f'rag/docs/aws/boto3_{svc.replace(\"-\",\"_\")}.txt'
        open(path,'w',encoding='utf-8').write(doc)
        print(f'  OK {path}')
    except Exception as e:
        print(f'  SKIP {svc}: {e}')
"

Write-Host "`nDone. Run: python -m rag.ingestor --all" -ForegroundColor Green
```

### `rag\ingestor.py` — implementation spec

```python
def ingest_platform_docs(platform: str, force: bool = False) -> int:
    """Returns number of chunks ingested."""
```

Implementation requirements:
1. Read env: `CHROMA_PERSIST_DIR`, `EMBED_MODEL`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`
2. Use `pathlib.Path` throughout — never hardcode backslashes
3. Walk `rag/docs/{platform}/` for `.md`, `.txt`, `.rst`, `.html`
4. Strip HTML tags for `.html` using stdlib `html.parser`
5. Split with `langchain.text_splitter.RecursiveCharacterTextSplitter`
6. Embed with `SentenceTransformer(EMBED_MODEL)` running on CPU
7. Upsert into ChromaDB collection `cloud_agents_{platform}`
8. Metadata: `{"source": str(path), "platform": platform, "chunk_index": i}`
9. Skip if collection exists and `force=False`
10. Print progress table via `rich.table.Table`

Windows note: ChromaDB's `persist_directory` accepts forward-slash paths on Windows.
Pass `str(Path(chroma_dir))` — pathlib normalises separators automatically.

CLI:
```powershell
python -m rag.ingestor --platform databricks
python -m rag.ingestor --all
python -m rag.ingestor --all --force
```

### `rag\retriever.py` — spec

```python
def retrieve(platform: str, query: str, top_k: int = None) -> list[dict]:
    """
    Returns: [{"content": str, "source": str, "score": float}, ...]
    Filtered: score >= 0.30
    Sorted: descending by score
    top_k: defaults to int(os.getenv("RAG_TOP_K", 5))
    """
```

---

## Phase 3 — Tool definitions

Pattern for every tool file:
- `TOOL_SCHEMAS: list[dict]` — Ollama `tools=` parameter format
- `TOOL_EXECUTORS: dict[str, Callable]` — name → function

Each executor: `def tool_name(**kwargs) -> dict`
- Env vars not set → `{"_mock": True, ...}` with realistic mock data (no exceptions)
- SDK success → JSON-serializable dict
- Any exception → `{"error": str(e), "tool": "tool_name"}`
- All live SDK calls → `concurrent.futures.ThreadPoolExecutor` with 15s timeout

**Windows note:** Use thread-based concurrency only (`ThreadPoolExecutor`).
`os.fork()` and multiprocessing with `spawn` context work on Windows but add overhead.
Threads are sufficient for wrapping synchronous SDK calls with timeouts.

### `tools\databricks_tools.py` — tools to implement

| Tool | Params | Mock return shape |
|---|---|---|
| `list_clusters` | none | `[{cluster_id, state, num_workers, driver_node_type}]` |
| `get_cluster_status` | `cluster_id: str` | `{state, cluster_id, driver, num_workers, uptime_s}` |
| `run_sql_statement` | `sql: str, warehouse_id: str` | `{rows: [], column_names: [], row_count: int}` |
| `list_uc_tables` | `catalog: str, schema: str` | `[{name, table_type, owner}]` |
| `get_uc_table_details` | `catalog: str, schema: str, table: str` | `{columns: [], row_count, owner}` |
| `list_mlflow_experiments` | none | `[{experiment_id, name, lifecycle_stage}]` |
| `get_mlflow_run` | `run_id: str` | `{params: {}, metrics: {}, tags: {}, artifact_uri}` |
| `list_jobs` | `limit: int = 20` | `[{job_id, name, schedule}]` |
| `trigger_job_run` | `job_id: int` | `{run_id, state}` |

### `tools\snowflake_tools.py` — tools to implement

| Tool | Params | Mock return shape |
|---|---|---|
| `execute_sql` | `sql: str, limit: int = 100` | `{rows: [], column_names: [], row_count: int}` |
| `list_databases` | none | `[{name, created_on, owner}]` |
| `list_schemas` | `database: str` | `[{name, database_name}]` |
| `describe_table` | `database: str, schema: str, table: str` | `{columns: [{name, type}], row_count}` |
| `cortex_complete` | `prompt: str, model: str = "mistral-large2"` | `{completion: str}` |
| `get_query_history` | `limit: int = 10` | `[{query_id, status, duration_ms}]` |
| `list_warehouses` | none | `[{name, state, size, auto_suspend}]` |
| `get_table_sample` | `database: str, schema: str, table: str, n: int = 5` | `{rows: [], column_names: []}` |

### `tools\aws_tools.py` — tools to implement

| Tool | Params | Mock return shape |
|---|---|---|
| `list_s3_buckets` | none | `[{name, creation_date, region}]` |
| `get_s3_object_count` | `bucket: str, prefix: str = ""` | `{object_count: int, total_size_bytes: int}` |
| `list_glue_databases` | none | `[{name, description}]` |
| `get_glue_table` | `database: str, table_name: str` | `{name, columns: [], location, row_count}` |
| `list_bedrock_models` | none | `[{model_id, provider, modalities}]` |
| `invoke_bedrock` | `model_id: str, prompt: str` | `{response: str, input_tokens: int}` |
| `get_iam_policy` | `policy_arn: str` | `{policy_name, document: {}}` |
| `list_lambda_functions` | `region: str = None` | `[{name, runtime, memory_mb}]` |
| `describe_ec2_instances` | `filters: list = []` | `[{instance_id, state, type, az}]` |

---

## Phase 4 — Agent implementation

### `agents\base_agent.py`

```python
import os, json, time
from abc import ABC, abstractmethod
from tenacity import retry, stop_after_attempt, wait_exponential
import ollama
from rag.retriever import retrieve

OLLAMA_BASE    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_ITERATIONS = 8


class BaseAgent(ABC):
    platform: str
    tool_schemas: list
    tool_executors: dict
    system_template: str   # must contain {rag_context}

    def __init__(self, model: str):
        self.model  = model
        self.client = ollama.Client(host=OLLAMA_BASE)
        self.register_tools()

    @abstractmethod
    def register_tools(self):
        pass

    def run(self, query: str, history: list = None) -> dict:
        t0 = time.time()
        tool_log = []

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
            msg  = resp.message

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
                name   = tc.function.name
                args   = tc.function.arguments or {}
                result = self._run_tool(name, args)
                tool_log.append({"name": name, "args": args, "result": result})
                messages.append({
                    "role":      "tool",
                    "tool_name": name,
                    "content":   json.dumps(result),
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
        )

    def _run_tool(self, name: str, args: dict) -> dict:
        fn = self.tool_executors.get(name)
        if not fn:
            return {"error": f"No executor registered for tool: {name}"}
        try:
            return fn(**args)
        except Exception as exc:
            return {"error": str(exc), "tool": name}

    def _fmt_rag(self, results: list) -> str:
        if not results:
            return "No relevant documentation retrieved."
        return "\n".join(
            f"[Source: {r['source']} | Score: {r['score']:.2f}]\n{r['content'].strip()}\n"
            for r in results[:5]
        )
```

### `agents\router.py`

```python
import os
import ollama

OLLAMA_BASE  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gemma4-agent")

KEYWORDS = {
    "databricks": {
        "databricks", "unity catalog", "delta lake", "delta table", "mlflow",
        "mosaic ai", "dbfs", "dlt", "lakeflow", "autoloader", "dbsql",
        "databricks sql", "medallion", "lakehouse"
    },
    "snowflake": {
        "snowflake", "cortex", "snowpark", "iceberg", "snowpipe",
        "virtual warehouse", "time travel", "zero-copy clone", "tasks",
        "streams", "dynamic tables", "cortex analyst"
    },
    "aws": {
        "aws", "amazon", "s3", "glue", "bedrock", "lambda", "ec2", "ecs",
        "iam", "cloudformation", "cdk", "sagemaker", "athena", "redshift",
        "step functions", "sns", "sqs", "kinesis", "lakeformation", "boto3"
    },
}

LLM_PROMPT = (
    "Classify this cloud infrastructure query into exactly one of: "
    "databricks, snowflake, aws.\n"
    "Reply with ONLY the category name, lowercase, nothing else.\n\n"
    "Query: {query}\nCategory:"
)


class Router:
    def __init__(self, model: str = ROUTER_MODEL):
        self.model  = model
        self.client = ollama.Client(host=OLLAMA_BASE)

    def route(self, query: str) -> str:
        """Returns 'databricks' | 'snowflake' | 'aws' | 'ambiguous'"""
        q      = query.lower()
        scores = {p: sum(1 for kw in kws if kw in q) for p, kws in KEYWORDS.items()}
        top    = max(scores, key=scores.get)

        if scores[top] > 0 and sum(v == scores[top] for v in scores.values()) == 1:
            return top

        # LLM fallback — tiny prompt, temperature=0
        resp  = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": LLM_PROMPT.format(query=query)}],
            options={"temperature": 0.0, "num_predict": 8},
        )
        token = resp.message.content.strip().lower().split()[0]
        return token if token in KEYWORDS else "ambiguous"
```

### Agent subclasses — pattern for all three

```python
from agents.base_agent import BaseAgent
from tools.{platform}_tools import TOOL_SCHEMAS, TOOL_EXECUTORS

class {Platform}Agent(BaseAgent):
    platform       = "{platform}"
    tool_schemas   = TOOL_SCHEMAS
    tool_executors = TOOL_EXECUTORS
    system_template = """
You are a {platform-specific persona}...
\n\nPlatform documentation context:\n{rag_context}
"""
    def register_tools(self):
        pass   # class-level attrs handle registration
```

**Databricks persona:** Unity Catalog three-part naming (catalog.schema.table), Delta Lake
ACID guarantees and time travel, MLflow experiment tracking and model registry, Structured
Streaming checkpoints, LakeFlow DLT pipelines. Security: never grant ALL PRIVILEGES broadly.

**Snowflake persona:** Cortex AI (COMPLETE, EMBED_TEXT, EXTRACT_ANSWER), Snowpark Python
UDFs and stored procedures, Iceberg external tables, virtual warehouse cost optimization,
clustering keys and materialized views. SQL rule: always include LIMIT on SELECT queries.

**AWS persona:** IAM least-privilege policies, S3 lifecycle rules and intelligent tiering,
Glue Data Catalog crawler patterns, Bedrock model invocation and agents, Lambda cold-start
mitigation, CDK L1/L2/L3 constructs. Rule: explain security implications of every IAM change.

---

## Phase 5 — Orchestration

### `orchestrator\session.py`

```python
from collections import deque

class Session:
    def __init__(self, max_turns: int = 10):
        self._history: deque = deque(maxlen=max_turns * 2)

    def append(self, user_msg: str, assistant_msg: str):
        self._history.extend([
            {"role": "user",      "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ])

    def get_history(self) -> list:
        return list(self._history)

    def clear(self):
        self._history.clear()
```

### `orchestrator\pipeline.py`

```python
import os
from agents.router           import Router
from agents.databricks_agent import DatabricksAgent
from agents.snowflake_agent  import SnowflakeAgent
from agents.aws_agent        import AWSAgent
from orchestrator.session    import Session

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemma4-agent")
_AMBIGUOUS  = (
    "I wasn't sure whether this relates to Databricks, Snowflake, or AWS. "
    "Could you mention the platform, or use the dropdown selector in the UI?"
)


class AgentPipeline:
    _instance = None

    def __init__(self):
        self.router  = Router()
        self.agents  = {
            "databricks": DatabricksAgent(model=AGENT_MODEL),
            "snowflake":  SnowflakeAgent(model=AGENT_MODEL),
            "aws":        AWSAgent(model=AGENT_MODEL),
        }
        self.session = Session()

    def run(self, query: str, platform_override: str = None) -> dict:
        platform = platform_override or self.router.route(query)
        if platform == "ambiguous":
            return {"platform": "ambiguous", "response": _AMBIGUOUS,
                    "tool_calls_made": [], "rag_sources": [], "latency_ms": 0}
        result           = self.agents[platform].run(query, self.session.get_history())
        result["platform"] = platform
        self.session.append(query, result["response"])
        return result

    def reset(self):
        self.session.clear()

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

---

## Phase 6 — Chat UI

### `ui\chat.py`

```python
"""
Launch: python ui\chat.py
Opens:  http://localhost:7860
"""
import gradio as gr
from orchestrator.pipeline import AgentPipeline


def respond(message: str, history: list, platform: str) -> str:
    override = None if platform == "auto" else platform
    result   = AgentPipeline.get().run(message, platform_override=override)

    body    = result["response"]
    tools   = ", ".join(t["name"] for t in result.get("tool_calls_made", []))
    # Use forward slash for display even on Windows paths
    sources = ", ".join(
        r["source"].replace("\\", "/").split("/")[-1]
        for r in result.get("rag_sources", [])[:3]
    )
    footer  = [
        f"**Platform:** `{result['platform']}`",
        f"**Latency:** {result['latency_ms']}ms",
    ]
    if tools:   footer.append(f"**Tools:** {tools}")
    if sources: footer.append(f"**RAG:** {sources}")

    return body + "\n\n---\n" + " | ".join(footer)


with gr.Blocks(title="Cloud Agent", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "## Cloud Platform Agent\n"
        "Gemma 4 26B A4B · AMD Ryzen AI MAX+ 395 · Windows 11 · Vulkan\n"
        "Databricks / Snowflake / AWS"
    )
    with gr.Row():
        sel = gr.Dropdown(
            choices=["auto", "databricks", "snowflake", "aws"],
            value="auto", label="Platform override", scale=1
        )
        rst = gr.Button("New session", variant="secondary", scale=1)

    gr.ChatInterface(
        fn=lambda msg, hist: respond(msg, hist, sel.value),
        type="messages",
        examples=[
            "List all tables in the bronze schema of the main catalog",
            "What Snowflake virtual warehouses are running right now?",
            "List my S3 buckets and their regions",
            "Show recent MLflow runs with validation accuracy above 0.95",
            "What Bedrock models are available in us-east-1?",
        ]
    )
    rst.click(fn=lambda: AgentPipeline.get().reset())

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
```

**Windows Firewall note:** If you cannot reach `http://localhost:7860` from another device
on your network, add a firewall rule in PowerShell (Admin):
```powershell
netsh advfirewall firewall add rule name="Gradio Agent" `
    dir=in action=allow protocol=TCP localport=7860
```
Localhost access always works without a firewall rule.

---

## Phase 7 — Evaluation

### Query file format (`eval\queries\{platform}_queries.json`)

30 entries per platform (10 single_tool, 10 multi_tool, 10 rag_only):

```json
[
  {
    "id": "db_001",
    "type": "single_tool",
    "query": "List all tables in the bronze schema of the main catalog",
    "expected_tool": "list_uc_tables",
    "required_args": ["catalog", "schema"],
    "expected_arg_values": {"schema": "bronze"}
  },
  {
    "id": "db_011",
    "type": "multi_tool",
    "query": "Find the latest MLflow run for experiment fx_model_v2 and show its metrics",
    "min_tool_calls": 2,
    "expected_tools_sequence": ["list_mlflow_experiments", "get_mlflow_run"]
  },
  {
    "id": "db_021",
    "type": "rag_only",
    "query": "What is Liquid Clustering in Delta Lake and when should I use it?",
    "expected_tool": null,
    "expected_rag_keyword": "liquid clustering"
  }
]
```

### `eval\evaluate.py` — metrics to compute

Per platform: tool selection accuracy, required-arg hit rate, routing accuracy, p50/p95 latency.
Output: rich table printed to terminal + `eval\results_{timestamp}.json` saved to disk.

---

## Claude Code execution sequence (Windows)

**Run in order. Stop and report on any failure. Do not skip steps.**

```powershell
# PHASE 0 — Hardware gate
.\infra\00_check_hardware.ps1
# --- MANUAL STEP: AMD Adrenalin VGM Custom 96 GB → Reboot ---
.\infra\00_check_hardware.ps1           # confirm GPU VRAM ~96 GB after reboot
# Run next as Administrator:
.\infra\02_install_ollama.ps1
# Open a NEW PowerShell window, then:
.\infra\03_pull_model.ps1
python infra\04_verify_toolcall.py      # MUST show 3/3 PASS
.\infra\05_benchmark_inference.ps1      # record baseline tok/s

# PHASE 1 — Scaffold
# Create pyproject.toml, .env.example, .gitignore
uv venv .venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -e .
python -c "import ollama, chromadb, gradio; print('All imports OK')"

# PHASE 2 — RAG
.\rag\fetch_docs.ps1
# Implement rag\ingestor.py and rag\retriever.py
python -m rag.ingestor --all
python -c "from rag.retriever import retrieve; r=retrieve('databricks','Delta Lake'); print(r[0]['score'], r[0]['source'])"

# PHASE 3 — Tools (mock mode)
# Implement tools\databricks_tools.py, snowflake_tools.py, aws_tools.py
pytest tests\test_tools_mock.py -v

# PHASE 4 — Agents
# Implement agents\base_agent.py, router.py, databricks_agent.py,
#           snowflake_agent.py, aws_agent.py
pytest tests\test_router.py -v
pytest tests\test_agents_mock.py -v

# PHASE 5 — Orchestration
# Implement orchestrator\session.py, pipeline.py

# PHASE 6 — UI
python ui\chat.py
# Manual: open http://localhost:7860, test one query per platform

# PHASE 7 — Evaluation
python eval\evaluate.py --mock
# Target: >80% tool selection accuracy in mock mode before live testing
```

---

## Windows environment variable reference

| Variable | Value | Where to set |
|---|---|---|
| `OLLAMA_VULKAN` | `1` | System env var (Machine scope) — mandatory |
| `OLLAMA_FLASH_ATTENTION` | `1` | System env var (Machine scope) |
| `OLLAMA_KEEP_ALIVE` | `60m` | System env var (Machine scope) |
| `OLLAMA_NUM_GPU` | `1` | System env var (Machine scope) |
| `OLLAMA_CONTEXT_LENGTH` | `32768` | System env var (start here; increase to 65536 if stable) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `.env` file |
| `AGENT_MODEL` | `gemma4-agent` | `.env` file |
| `CHROMA_PERSIST_DIR` | `.\rag\chroma_db` | `.env` file |

Set system env vars via Settings GUI or PowerShell (Admin):
```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN","1","Machine")
```
Then open a **new** terminal — existing sessions do not inherit new machine-scope vars.

---

## Windows-specific known issues

**1. New terminal required after env var changes.**
Machine-scope environment variables set via `[Environment]::SetEnvironmentVariable`
only appear in processes launched after the write. Always open a fresh PowerShell
window after running `02_install_ollama.ps1`. Verify: `$env:OLLAMA_VULKAN` prints `1`.

**2. Ollama is a tray app, not a service, on Windows.**
It auto-starts at login. To manually start: run `ollama serve` in a terminal, or
find Ollama in Start Menu. Logs: `%USERPROFILE%\.ollama\logs\server.log`.
After changing env vars: right-click Ollama tray icon → Quit → reopen from Start Menu.

**3. AMD Adrenalin driver version.**
VGM Custom 96 GB requires Adrenalin 25.8.1 WHQL or later. Earlier drivers may cap
VGM lower. Verify in Device Manager > Display Adapters > Radeon 8060S > Driver version.

**4. Ollama must be >= 0.20.2.**
Earlier versions have Gemma 4 tool-call parser bugs. Update:
```powershell
winget upgrade Ollama.Ollama
```

**5. ChromaDB path separators.**
Use `pathlib.Path` everywhere. Do not use raw backslash strings for paths.
`Path("rag\\chroma_db")` and `Path("rag/chroma_db")` both work on Windows.

**6. GPU column shows 0 or CPU in `ollama ps`.**
Most common cause: `OLLAMA_VULKAN` env var not set, or Ollama was not restarted
after it was set. Check `server.log` for lines containing `vulkan` or `GPU`.
If Vulkan is active you will see: `library=Vulkan name=Vulkan0 description="AMD Radeon..."`.

**7. Context length above 32768.**
Safe to increase to 65536 once the baseline test passes. Set via:
```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","65536","Machine")
```
Then restart Ollama. Monitor RAM during inference — all three agents warm + 65K context
uses ~55–65 GB. Should still fit within 96 GB VGM with headroom for Windows.

---

*Platform: Windows 11 Native (no WSL)*
*Hardware: AMD Ryzen AI MAX+ 395 (gfx1151) · 128 GB LPDDR5X-8000 · Radeon 8060S*
*GPU acceleration: Vulkan only — ROCm not available for AMD APUs on Windows*
*VRAM: 96 GB maximum via AMD Variable Graphics Memory (Windows ceiling)*
*Model: Gemma 4 26B A4B (MoE) · Ollama 0.20.2+*
*Project: Cloud Platform Agents — Databricks / Snowflake / AWS*
*Author: Terrence Kim · April 2026*
