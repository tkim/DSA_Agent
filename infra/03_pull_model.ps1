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
