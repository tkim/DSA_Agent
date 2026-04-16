Write-Host "--- Machine scope OLLAMA vars ---" -ForegroundColor Cyan
foreach ($k in @("OLLAMA_VULKAN","OLLAMA_FLASH_ATTENTION","OLLAMA_KEEP_ALIVE","OLLAMA_NUM_GPU","OLLAMA_CONTEXT_LENGTH")) {
    $v = [Environment]::GetEnvironmentVariable($k, "Machine")
    Write-Host ("  {0,-25} = {1}" -f $k, $v)
}

Write-Host "`n--- User scope OLLAMA vars ---" -ForegroundColor Cyan
foreach ($k in @("OLLAMA_VULKAN","OLLAMA_FLASH_ATTENTION","OLLAMA_KEEP_ALIVE","OLLAMA_NUM_GPU","OLLAMA_CONTEXT_LENGTH")) {
    $v = [Environment]::GetEnvironmentVariable($k, "User")
    Write-Host ("  {0,-25} = {1}" -f $k, $v)
}

Write-Host "`n--- Process scope OLLAMA vars ---" -ForegroundColor Cyan
Get-ChildItem Env: | Where-Object { $_.Name -like "OLLAMA*" } | Format-Table -AutoSize

Write-Host "--- Is ollama.exe running? ---" -ForegroundColor Cyan
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Format-Table Id, Name, StartTime -AutoSize

Write-Host "`n--- Ollama API ---" -ForegroundColor Cyan
try {
    $r = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -Method GET -TimeoutSec 3
    Write-Host "API version: $($r.version)" -ForegroundColor Green
} catch {
    Write-Host "API not reachable: $_" -ForegroundColor Yellow
}
