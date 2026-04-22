# Cloud Platform Agent

A fully local, offline-capable AI agent for querying **Databricks**, **Snowflake**, and **AWS** infrastructure — running on AMD Ryzen AI MAX+ 395 hardware via Ollama + Vulkan.

No cloud API keys required for the AI layer. No web server. No internet connection needed after initial setup.

---

## Hardware target

| Component | Spec |
|---|---|
| CPU | AMD Ryzen AI MAX+ 395 (16 × Zen 5) |
| GPU | Radeon 8060S — **Vulkan only** on Windows (no ROCm) |
| Memory | 128 GB LPDDR5X-8000 unified |
| VRAM | 96 GB via AMD Variable Graphics Memory (VGM) |
| OS | Windows 11 Native — no WSL |

**Model:** Gemma 4 26B A4B (MoE) · ~17 GB at Q4\_K\_M · 100% GPU via Vulkan · **41 tok/s**

---

## Repository layout

```
├── cli.py                        ← launch point (python cli.py)
├── pyproject.toml
├── .env.example                  ← copy to .env and fill credentials
│
├── agents/
│   ├── base_agent.py             ← tool-calling loop, RAG injection, retry
│   ├── router.py                 ← keyword + LLM-fallback router
│   ├── databricks_agent.py
│   ├── snowflake_agent.py
│   └── aws_agent.py
│
├── tools/
│   ├── _common.py                ← mock-safe wrapper, timeout helper
│   ├── databricks_tools.py       ← 9 tools
│   ├── snowflake_tools.py        ← 8 tools
│   └── aws_tools.py              ← 9 tools
│
├── rag/
│   ├── fetch_docs.ps1            ← one-time doc download
│   ├── ingestor.py               ← chunk → embed → ChromaDB
│   └── retriever.py              ← cosine similarity query
│
├── orchestrator/
│   ├── session.py                ← conversation history (deque)
│   └── pipeline.py               ← router + agents + session wired together
│
├── infra/
│   ├── 00_check_hardware.ps1
│   ├── 01_setup_vgm.md           ← AMD Adrenalin VGM manual steps
│   ├── 02_install_ollama.ps1
│   ├── 03_pull_model.ps1
│   ├── 04_verify_toolcall.py     ← gate test (must show 3/3 PASS)
│   └── 05_benchmark_inference.ps1
│
├── eval/
│   ├── evaluate.py
│   └── queries/{databricks,snowflake,aws}_queries.json
│
└── tests/
    ├── test_tools_mock.py
    ├── test_agents_mock.py
    └── test_router.py
```

---

## One-time setup

> All steps below require internet. After completing them the system runs fully offline.

### 1. AMD Adrenalin — set VRAM to 96 GB (manual, requires reboot)

Open **AMD Software: Adrenalin Edition** → Performance → Tuning → System →
Variable Graphics Memory → Custom → **96 GB** → Apply → Restart.

Verify after reboot:
```powershell
.\infra\00_check_hardware.ps1
```

### 2. Install Ollama (run as Administrator)

```powershell
.\infra\02_install_ollama.ps1
```

Sets `OLLAMA_VULKAN=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KEEP_ALIVE=60m`,
`OLLAMA_NUM_GPU=1`, `OLLAMA_CONTEXT_LENGTH=32768` at Machine scope.

Open a **new** PowerShell window after this step (env vars need a fresh session).

### 3. Pull the model

```powershell
.\infra\03_pull_model.ps1
```

Downloads `gemma4:26b` (~17 GB), creates the `gemma4-agent` Modelfile,
and warms the model into VRAM. Verify GPU placement:

```powershell
ollama ps
# NAME              SIZE   PROCESSOR   CONTEXT
# gemma4-agent      20 GB  100% GPU    32768
```

### 4. Verify tool calling (must show 3/3 PASS)

```powershell
python infra\04_verify_toolcall.py
```

Do not proceed until all three tests pass.

### 5. Create Python environment

Install Python 3.11 system-wide (stable path, never moves):
```powershell
winget install Python.Python.3.11 --scope machine
```

Create the venv using the system Python (not uv-managed — avoids AppData path breakage):
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -e .
```

### 6. Configure environment

```powershell
copy .env.example .env
```

Edit `.env` — fill in your Databricks / Snowflake / AWS credentials.
Leave credentials blank to run in **mock mode** (no live platform access needed).

The two offline flags in `.env` are already set:
```ini
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

These prevent the embedding model from attempting any HuggingFace network calls.

### 7. Build the RAG corpus (one-time doc fetch + ingest)

```powershell
.\rag\fetch_docs.ps1
python -m rag.ingestor --all
```

Downloads Delta Lake, Snowflake, and AWS documentation and embeds it into a local
ChromaDB at `rag/chroma_db/`. Also caches the `all-MiniLM-L6-v2` embedding model
to `%USERPROFILE%\.cache\huggingface\`. After this step no network access is needed.

---

## Launching the agent

```powershell
cd "C:\Users\tckim\OneDrive\Documents\GitHub\DSA_Agent\.claude\worktrees\upbeat-ellis"
.\.venv\Scripts\python.exe cli.py
```

Optional — lock to a specific platform:
```powershell
.\.venv\Scripts\python.exe cli.py --platform databricks
.\.venv\Scripts\python.exe cli.py --platform snowflake
.\.venv\Scripts\python.exe cli.py --platform aws
```

### What happens at startup

```
1. all-MiniLM-L6-v2 loaded into RAM      (from local HF cache, ~5s)
2. ChromaDB client connected              (local rag/chroma_db/, instant)
3. gemma4-agent loaded into GPU VRAM     (keep_alive=120m, ~5-10s)
4. you> prompt appears — ready to query
```

The model stays in VRAM for 2 hours of inactivity. Subsequent queries are immediate.

### CLI commands

| Input | Effect |
|---|---|
| Any question | Auto-routed to Databricks / Snowflake / AWS |
| `/platform aws` | Lock platform for the rest of the session |
| `/platform auto` | Return to auto-routing |
| `/reset` | Clear conversation history |
| `/quit` or `Ctrl-C` | Exit |

---

## How it works

### Routing

Every query is first scored against a keyword dictionary (Databricks, Snowflake, AWS terms).
Strong platform identifiers (e.g. `unity catalog`, `cortex`, `bedrock`) score 2× to break
ties. If no platform wins clearly, the router falls back to a zero-temperature Ollama call
with a 3-token classification prompt.

### Agent loop

Each platform agent runs a tool-calling loop (max 8 iterations):

```
query → RAG retrieval → system prompt + context → LLM
  → tool call? → execute tool → inject result → LLM
  → tool call? → ...
  → text response → return
```

RAG context (top-5 chunks, score ≥ 0.30) is injected into the system prompt on every turn.
All LLM calls use `keep_alive=60m` to guarantee the model stays in VRAM across turns.

### Tools (mock-safe)

All tools check for credentials at call time. Missing env vars → realistic mock data returned,
no exception raised. This means the agent is fully testable without any live platform access.

| Platform | Tools |
|---|---|
| Databricks | list\_clusters, get\_cluster\_status, run\_sql\_statement, list\_uc\_tables, get\_uc\_table\_details, list\_mlflow\_experiments, get\_mlflow\_run, list\_jobs, trigger\_job\_run |
| Snowflake | execute\_sql, list\_databases, list\_schemas, describe\_table, cortex\_complete, get\_query\_history, list\_warehouses, get\_table\_sample |
| AWS | list\_s3\_buckets, get\_s3\_object\_count, list\_glue\_databases, get\_glue\_table, list\_bedrock\_models, invoke\_bedrock, get\_iam\_policy, list\_lambda\_functions, describe\_ec2\_instances |

---

## Running tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

All 35 tests run fully offline — no Ollama, no platform credentials, no network.

---

## Offline asset checklist

Everything below must be in place before going offline:

| Asset | Location | Populated by |
|---|---|---|
| Ollama binary | `C:\Users\...\AppData\Local\Programs\Ollama\` | `02_install_ollama.ps1` |
| gemma4:26b weights | `%USERPROFILE%\.ollama\models\` | `03_pull_model.ps1` |
| gemma4-agent Modelfile | registered in Ollama | `03_pull_model.ps1` |
| all-MiniLM-L6-v2 | `%USERPROFILE%\.cache\huggingface\hub\` | `rag/ingestor.py` first run |
| ChromaDB collections | `rag/chroma_db/` | `python -m rag.ingestor --all` |
| Python venv | `.venv/` | `py -3.11 -m venv .venv` + `pip install -e .` |

Verify at any time:
```powershell
ollama list          # gemma4:26b and gemma4-agent must appear
ollama ps            # GPU column should show ~20 GB while running
python -m pytest tests/ -v   # 35/35 must pass
```

---

## Performance (AMD Ryzen AI MAX+ 395 · Windows 11 · Vulkan)

| Metric | Value |
|---|---|
| Token generation | ~42 tok/s |
| Prompt processing | ~1,750 tok/s |
| Model VRAM usage | ~20 GB (of 96 GB available) |
| Typical query latency | 3–8s (model warm) |
| Cold start (model load) | ~5–10s (at CLI launch only) |

---

## Environment variables reference

| Variable | Value | Set in |
|---|---|---|
| `OLLAMA_VULKAN` | `1` | Machine env (02\_install\_ollama.ps1) |
| `OLLAMA_FLASH_ATTENTION` | `1` | Machine env |
| `OLLAMA_KEEP_ALIVE` | `60m` | Machine env |
| `OLLAMA_NUM_GPU` | `1` | Machine env |
| `OLLAMA_CONTEXT_LENGTH` | `32768` | Machine env |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `.env` |
| `AGENT_MODEL` | `gemma4-agent` | `.env` |
| `CHROMA_PERSIST_DIR` | `.\rag\chroma_db` | `.env` |
| `HF_HUB_OFFLINE` | `1` | `.env` — blocks HuggingFace network after setup |
| `TRANSFORMERS_OFFLINE` | `1` | `.env` — same |
