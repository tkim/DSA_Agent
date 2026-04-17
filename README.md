# DSA_Agent

**A fully local, multi-agent system for Databricks, Snowflake, and AWS.**

DSA_Agent turns natural-language questions into real operations across the three platforms without sending a byte to any hosted LLM. A router model reads the question, hands it to the right specialist (Databricks, Snowflake, or AWS), and the specialist executes the request using official platform SDKs, grounded by a local RAG index of platform documentation. Everything — model inference, embeddings, vector store, and UI — runs on your own machine.

## Why

Cross-cloud data work usually means switching between three consoles, three SQL dialects, and three sets of docs. DSA_Agent collapses that into one chat box while keeping credentials, prompts, and query results on your hardware. It is designed for the **AMD Ryzen AI MAX+ 395** (Radeon 8060S iGPU + 128 GB unified memory), but runs on any reasonably capable PC that can host Ollama.

## Features

- **Three specialist agents** — Databricks (clusters, jobs, Delta tables), Snowflake (warehouses, SQL, schemas), and AWS (S3, Glue, Athena, IAM inspection).
- **Local LLM inference** — Gemma 4 26B A4B served by Ollama with Vulkan GPU acceleration on Windows.
- **RAG grounding** — ChromaDB + `sentence-transformers` index of Databricks/Snowflake/AWS docs for accurate, citation-backed answers.
- **Mock mode** — every tool has a mocked implementation so agents, routing, and the UI can be developed and tested without real cloud credentials.
- **Gradio chat UI** — browser-based chat at `http://localhost:7860`.
- **Offline evaluation harness** — JSON query suites per platform with tool-selection accuracy metrics.

## Architecture

```
                  ┌─────────────────────────┐
    user prompt → │  Gradio UI (ui/chat.py) │
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │  orchestrator/pipeline  │ ── session memory
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │    agents/router.py     │  ← Gemma 4 (routing)
                  └───┬───────────┬─────────┘
                      │           │           └──────────────┐
                      ▼           ▼                          ▼
         ┌────────────────┐ ┌───────────────┐  ┌────────────────┐
         │ databricks_agt │ │ snowflake_agt │  │   aws_agent    │ ← Gemma 4 + tools
         └────────┬───────┘ └───────┬───────┘  └────────┬───────┘
                  ▼                 ▼                   ▼
           databricks_tools  snowflake_tools        aws_tools
                  │                 │                   │
                  ▼                 ▼                   ▼
             databricks-sdk   snowflake-conn.       boto3
                                      │
                                      ▼
                             ┌─────────────────┐
                             │ RAG (ChromaDB)  │ ← per-platform docs
                             └─────────────────┘
```

## Repository layout

```
DSA_Agent/
├── agents/          router + one specialist per platform
├── tools/           databricks / snowflake / aws SDK wrappers (with mock fallback)
├── rag/             ingestor, retriever, ChromaDB persistence
├── orchestrator/    session memory + request pipeline
├── ui/chat.py       Gradio chat front-end
├── eval/            JSON query sets + accuracy harness
├── infra/           PowerShell scripts: hardware check, Ollama install, model pull, benchmarks
├── tests/           pytest suites (mock-based)
├── pyproject.toml
├── .env.example
└── CLAUDE.md        deep engineering spec (implementation-level reference)
```

---

## Local PC Deployment

Two supported Windows 11 paths are documented below:

- **Path A — AMD Radeon (Vulkan).** Reference target: Ryzen AI MAX+ 395 + Radeon 8060S iGPU. This is the configuration the `infra\*.ps1` scripts were built for.
- **Path B — NVIDIA (CUDA).** Any RTX 3080 or newer consumer card (Ampere, Ada Lovelace, Blackwell). No AMD-specific tooling; Ollama's bundled CUDA runtime handles acceleration.

Steps 1, 4–11 are **common to both paths**. Steps 2 and 3 fork — follow the subsection that matches your GPU. A Linux note appears at the end.

### Prerequisites

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Windows 11 22H2 | Windows 11 24H2 |
| CPU | 8-core x86-64 | Ryzen AI MAX+ 395 (16-core Zen 5) / Core i7-13700K+ |
| RAM | 32 GB | 64 GB (NVIDIA discrete) / 128 GB unified (AMD APU) |
| GPU | RTX 3080 10 GB **or** Vulkan-capable AMD GPU (or CPU-only) | RTX 4090 / RTX 5090 / Radeon 8060S |
| VRAM | 10 GB (partial offload) | 24 GB+ for full Gemma 4 26B at Q4_K_M |
| Disk | 40 GB free | 100 GB on NVMe |
| Python | 3.11 | 3.11 |
| Ollama | 0.20.2+ (Gemma 4 tool-calling fix) | latest |
| AMD driver (Path A) | Adrenalin 25.8.1 WHQL (for VGM 96 GB) | latest |
| NVIDIA driver (Path B) | 555.xx (Windows) / 555.xx (Linux) | 560.xx+ |

> **Do not use WSL2** on the AMD path. All PowerShell scripts assume native Windows. ROCm is not supported on AMD integrated GPUs on Windows; the GPU path there is **Vulkan only** (`OLLAMA_VULKAN=1`). WSL2 with NVIDIA CUDA works but is outside the scope of this guide.

### Step 1 — Clone the repo

```powershell
git clone https://github.com/tkim/DSA_Agent.git
cd DSA_Agent
```

### Step 2 — Hardware and driver gate

#### Path A — AMD Radeon (Vulkan)

Open PowerShell and run:

```powershell
.\infra\00_check_hardware.ps1
```

This reports CPU, GPU, VRAM, AMD driver version, Ollama version, and whether `OLLAMA_VULKAN` is set. Fix any red lines before moving on.

Follow the manual steps in `infra\01_setup_vgm.md` to raise the Variable Graphics Memory to 96 GB in AMD Adrenalin, then reboot and re-run the check.

#### Path B — NVIDIA (CUDA)

There's no VGM step and you don't need to install the CUDA Toolkit separately — Ollama ships with its own CUDA runtime. You only need a current driver:

1. Download the latest **NVIDIA Game Ready** or **Studio** driver from <https://www.nvidia.com/Download/index.aspx> (555.xx or newer; 560.xx+ recommended for RTX 50-series).
2. Install it, then reboot.
3. Verify with:

   ```powershell
   nvidia-smi
   ```

   You should see your GPU, driver version, total VRAM, and CUDA version (12.x). If `nvidia-smi` is not found, the driver install didn't complete — reinstall before continuing.

Target free VRAM for a comfortable Gemma 4 26B at Q4_K_M: **~18 GB**. See the quantization guidance in Step 4 for how to adapt on smaller cards.

### Step 3 — Install Ollama and configure GPU

#### Path A — AMD Radeon (Vulkan)

Run as **Administrator** (installs Ollama and sets system-scope environment variables):

```powershell
.\infra\02_install_ollama.ps1
```

The script sets the following machine-scope variables:

| Variable | Value | Purpose |
|---|---|---|
| `OLLAMA_VULKAN` | `1` | Enables Vulkan backend (mandatory on AMD Windows) |
| `OLLAMA_FLASH_ATTENTION` | `1` | Faster attention kernels |
| `OLLAMA_KEEP_ALIVE` | `60m` | Keeps the model warm between turns |
| `OLLAMA_NUM_GPU` | `1` | Offloads all layers to GPU |
| `OLLAMA_CONTEXT_LENGTH` | `32768` | Start here; raise to 65536 if stable |

Close the terminal and **open a fresh PowerShell window** — machine-scope variables only show up in processes launched after they are written.

#### Path B — NVIDIA (CUDA)

Install Ollama — the CUDA backend is the default when an NVIDIA GPU is present, so no `OLLAMA_VULKAN` is needed. Run in an **Administrator** PowerShell:

```powershell
winget install Ollama.Ollama --silent `
    --accept-package-agreements --accept-source-agreements
ollama --version   # must be >= 0.20.2
```

Then set the recommended machine-scope environment variables. Adjust `OLLAMA_KEEP_ALIVE` downward on cards with tight VRAM so the model can unload between calls:

```powershell
# Common
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","1","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","32768","Machine")

# 24 GB+ cards (RTX 3090 / 4090 / 5090) — keep the model warm
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE","60m","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","2","Machine")

# 10–16 GB cards (RTX 3080 / 4070 Ti / 4080 / 5080) — swap between models
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE","10m","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","Machine")
```

> **Do not set `OLLAMA_VULKAN=1` on NVIDIA.** It forces the Vulkan backend and disables CUDA.

Restart Ollama (right-click tray icon → Quit → relaunch from Start Menu) and open a fresh PowerShell window. Verify CUDA is active:

```powershell
ollama run gemma4:26b "hi" --verbose
# Expect a log line like:  library=cuda name=CUDA0 description="NVIDIA GeForce RTX ..."
```

You can also check live utilization while a query is running:

```powershell
nvidia-smi -l 1
```

### Step 4 — Pull the model

```powershell
.\infra\03_pull_model.ps1
```

Pulls `gemma4:26b` (~17 GB at Q4_K_M) and builds the `gemma4-agent` Modelfile used by the router and specialists.

**VRAM sizing guide (NVIDIA):**

| GPU | VRAM | Recommended model tag | Notes |
|---|---|---|---|
| RTX 3080 10 GB | 10 GB | `gemma2:9b` or `llama3.1:8b-instruct-q4_K_M` | 26B won't fit fully; swap `AGENT_MODEL` in `.env` |
| RTX 3080 Ti / 4070 Ti | 12 GB | `gemma2:9b` (headroom) or `gemma4:26b` with partial offload | 26B runs but spills to CPU — slow |
| RTX 4080 / 5080 | 16 GB | `gemma4:26b` Q4_K_M (tight) or `gemma4:26b` Q3_K_M | Tune `OLLAMA_CONTEXT_LENGTH` down to `16384` if OOM |
| RTX 3090 / 4090 | 24 GB | `gemma4:26b` Q4_K_M (default) | Full 32K context fits comfortably |
| RTX 5090 | 32 GB | `gemma4:26b` Q5_K_M or two specialists loaded simultaneously | Set `OLLAMA_MAX_LOADED_MODELS=2` |

If you pick a different base model, edit `infra\modelfiles\Gemma4Agent.modelfile` and change the `FROM` line, then re-run:

```powershell
ollama create gemma4-agent -f infra\modelfiles\Gemma4Agent.modelfile
```

Smaller models than Gemma 4 26B may degrade tool-call accuracy — re-run Step 5's gate test to confirm 3/3 pass before continuing.

### Step 5 — Verify tool calling (mandatory gate)

```powershell
python .\infra\04_verify_toolcall.py
```

You **must** see `3/3 PASS`. If not, stop and fix before proceeding — the agents cannot function without working tool calls. Also run:

```powershell
.\infra\05_benchmark_inference.ps1
```

to record a baseline tokens/second number.

### Step 6 — Python environment

Using `uv` (recommended):

```powershell
winget install astral-sh.uv
uv venv .venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -e .
python -c "import ollama, chromadb, gradio; print('All imports OK')"
```

Or using Miniconda:

```powershell
conda create -n cloud-agents python=3.11 -y
conda activate cloud-agents
pip install -e .
```

### Step 7 — Configure credentials

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in the sections you intend to use. **Leave any section blank to keep that platform in mock mode** — useful for first-run testing.

```ini
# Inference
OLLAMA_BASE_URL=http://localhost:11434
AGENT_MODEL=gemma4-agent
ROUTER_MODEL=gemma4-agent

# RAG
CHROMA_PERSIST_DIR=.\rag\chroma_db
EMBED_MODEL=all-MiniLM-L6-v2
RAG_TOP_K=5

# Databricks (blank = mock)
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

`.env` is already gitignored. Never commit it.

### Step 8 — Build the RAG index

```powershell
.\rag\fetch_docs.ps1
python -m rag.ingestor --all
```

This downloads Databricks/Snowflake/AWS reference docs into `rag\docs\` and ingests them into a local ChromaDB at `rag\chroma_db\`. To re-index from scratch later, use `--force`:

```powershell
python -m rag.ingestor --all --force
```

Quick sanity check:

```powershell
python -c "from rag.retriever import retrieve; r=retrieve('databricks','Delta Lake'); print(r[0]['score'], r[0]['source'])"
```

### Step 9 — Run the test suite

```powershell
pytest tests\test_tools_mock.py -v
pytest tests\test_router.py -v
pytest tests\test_agents_mock.py -v
```

All three suites run in mock mode and should pass before you wire in real credentials.

### Step 10 — Launch the chat UI

```powershell
python ui\chat.py
```

Open `http://localhost:7860` in a browser. Try one query per platform:

- "List the running clusters in Databricks."
- "Show me the row count of `SALES.ORDERS` in Snowflake."
- "Which S3 buckets exist in us-east-1?"

### Step 11 — (Optional) Run the evaluation harness

```powershell
python eval\evaluate.py --mock
```

Target: **>80% tool-selection accuracy** in mock mode before moving to live credentials.

---

## Everyday commands

```powershell
# Activate the venv
.\.venv\Scripts\Activate.ps1

# Launch the chat UI
python ui\chat.py

# Re-ingest docs after refreshing them
.\rag\fetch_docs.ps1
python -m rag.ingestor --all --force

# Check which model is loaded and on which device
ollama ps
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ollama ps` shows GPU column as `0` or `CPU` (AMD) | `OLLAMA_VULKAN` not set, or Ollama not restarted | Re-run `infra\02_install_ollama.ps1`; quit & relaunch Ollama from Start Menu |
| `ollama ps` shows GPU column as `0` or `CPU` (NVIDIA) | Driver older than 555.xx, or `OLLAMA_VULKAN=1` accidentally set | Update the NVIDIA driver; `[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN",$null,"Machine")` to clear the flag |
| CUDA out-of-memory on model load | VRAM too small for chosen quant | Switch to a smaller tag (see Step 4 sizing guide) or lower `OLLAMA_CONTEXT_LENGTH` |
| `nvidia-smi` not found | Driver install failed or not on PATH | Reinstall the driver; reboot |
| Very slow token generation on NVIDIA | Model partially offloaded to CPU | Check with `ollama ps` — GPU % should be 100%; if not, pick a smaller quant |
| `3/3 PASS` fails in `04_verify_toolcall.py` | Ollama < 0.20.2 (Gemma 4 tool-call parser bug) | `winget upgrade Ollama.Ollama`, then retry |
| VGM stuck below 96 GB | AMD Adrenalin driver too old | Install Adrenalin 25.8.1 WHQL or later, reboot, redo VGM setup |
| `python -c "import ollama..."` errors | venv not activated | `.\.venv\Scripts\Activate.ps1` |
| Snowflake `250001` login failure | Wrong account identifier format | Use `<org>-<account>`, not the full URL |
| AWS `NoCredentialsError` | `.env` not loaded | Confirm `.env` is in repo root, restart the shell |
| ChromaDB path errors on Windows | Raw-string backslashes in paths | Use `pathlib.Path`; both `/` and `\\` work |
| New env var not visible | Machine-scope vars only appear in fresh processes | Open a new PowerShell window |

Ollama logs: `%USERPROFILE%\.ollama\logs\server.log`. To confirm GPU acceleration is live, look for:

- **AMD/Vulkan:** `library=Vulkan name=Vulkan0 description="AMD Radeon..."`
- **NVIDIA/CUDA:** `library=cuda name=CUDA0 description="NVIDIA GeForce RTX..."`

## Linux note

Linux users can substitute `venv` + `pip install -e .` for steps 6–7 and run Ollama via its official Linux installer (`curl -fsSL https://ollama.com/install.sh | sh`). GPU setup:

- **NVIDIA:** install the proprietary driver from your distro (555.xx+) plus `nvidia-container-toolkit` if you want Ollama in Docker. CUDA is auto-detected. Verify with `nvidia-smi`.
- **AMD discrete (RX 7000 / 9000):** ROCm works natively; `OLLAMA_VULKAN` is not required.
- **AMD APUs (Ryzen AI MAX+):** Vulkan is still the supported path; set `OLLAMA_VULKAN=1`.

The PowerShell scripts in `infra\` are Windows-specific — translate them to shell as needed. Everything under `agents/`, `tools/`, `rag/`, `orchestrator/`, `ui/`, and `eval/` is OS-agnostic Python.

## Deeper engineering spec

`CLAUDE.md` contains the full implementation specification: exact tool signatures, router prompt, Modelfile, evaluation format, and Windows-specific pitfalls. Start there if you plan to extend an agent or add a new platform.

## License

See `LICENSE`.
