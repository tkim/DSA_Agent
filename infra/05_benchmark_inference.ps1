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
