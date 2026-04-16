$vars = [ordered]@{
    OLLAMA_VULKAN          = "1"
    OLLAMA_FLASH_ATTENTION = "1"
    OLLAMA_KEEP_ALIVE      = "60m"
    OLLAMA_NUM_GPU         = "1"
    OLLAMA_CONTEXT_LENGTH  = "32768"
}
foreach ($k in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($k, $vars[$k], "User")
    Write-Host ("Set User {0} = {1}" -f $k, $vars[$k])
}

Write-Host "`nRestarting Ollama to pick up new env vars..." -ForegroundColor Cyan
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
# Spawn new ollama process that will inherit the User env vars
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 4

Write-Host "`nVerify:"
foreach ($k in $vars.Keys) {
    $v = [Environment]::GetEnvironmentVariable($k, "User")
    Write-Host ("  {0,-25} = {1}" -f $k, $v)
}
try {
    $r = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -Method GET -TimeoutSec 5
    Write-Host "API OK: $($r.version)" -ForegroundColor Green
} catch {
    Write-Warning "API not reachable: $_"
}
