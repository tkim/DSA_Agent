#Requires -RunAsAdministrator

# -- Install Ollama -----------------------------------------------------------
Write-Host "Installing Ollama for Windows..." -ForegroundColor Cyan
winget install Ollama.Ollama `
    --silent `
    --accept-package-agreements `
    --accept-source-agreements

# Refresh PATH in this session
$machinePath = [Environment]::GetEnvironmentVariable("PATH","Machine")
$userPath    = [Environment]::GetEnvironmentVariable("PATH","User")
$env:PATH    = "$machinePath;$userPath"

# -- Version gate -------------------------------------------------------------
$rawVer  = (& ollama --version 2>&1) -replace "ollama version ",""
$semVer  = [Version]($rawVer -replace "^(\d+\.\d+\.\d+).*",'$1')
$minVer  = [Version]"0.20.2"
Write-Host "Ollama version: $rawVer"
if ($semVer -lt $minVer) {
    Write-Host "Version $rawVer < 0.20.2. Attempting upgrade..." -ForegroundColor Yellow
    winget upgrade Ollama.Ollama `
        --silent `
        --accept-package-agreements `
        --accept-source-agreements
    $rawVer  = (& ollama --version 2>&1) -replace "ollama version ",""
    $semVer  = [Version]($rawVer -replace "^(\d+\.\d+\.\d+).*",'$1')
    if ($semVer -lt $minVer) {
        Write-Error "Version $rawVer < 0.20.2 even after upgrade. Gemma 4 tool calling will fail."
        exit 1
    }
}
Write-Host "Version OK" -ForegroundColor Green

# -- Set system-level environment variables -----------------------------------
# These persist across reboots and apply to all users.
# IMPORTANT: Ollama must be restarted after setting these (tray -> Quit -> reopen).
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

# -- Restart Ollama tray app to pick up new vars ------------------------------
Write-Host "`nRestarting Ollama..." -ForegroundColor Cyan
Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 4

# -- Verify API ---------------------------------------------------------------
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/version" -Method GET
    Write-Host "Ollama API OK - version: $($resp.version)" -ForegroundColor Green
} catch {
    Write-Warning "Ollama API not reachable. Try opening Ollama from Start Menu."
}

Write-Host @"

Next steps:
  1. Open a NEW PowerShell window (env vars only take effect in new sessions)
  2. Verify: `$env:OLLAMA_VULKAN   should print  1
  3. Run:    .\infra\03_pull_model.ps1
"@ -ForegroundColor Yellow
