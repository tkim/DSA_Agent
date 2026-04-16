#Requires -Version 5.1
Write-Host "=== Ryzen AI MAX+ 395 - Windows Hardware Check ===" -ForegroundColor Cyan

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
    "Cannot read GPU VRAM via WMI - check AMD Adrenalin app directly"
}

Write-Host "`n--- AMD Driver ---"
$drv = (Get-WmiObject Win32_VideoController |
    Where-Object { $_.Name -match "AMD|Radeon" }).DriverVersion
"Driver: $drv  (need Adrenalin 25.8.1 WHQL or later)"

Write-Host "`n--- Ollama ---"
try {
    $ver = (& ollama --version 2>&1) -replace "ollama version ",""
    "Ollama: $ver  (need >= 0.20.2 for Gemma 4 tool calling)"
} catch { "Ollama not installed - run 02_install_ollama.ps1" }

Write-Host "`n--- Vulkan env var ---"
$sys  = [Environment]::GetEnvironmentVariable("OLLAMA_VULKAN","Machine")
$user = [Environment]::GetEnvironmentVariable("OLLAMA_VULKAN","User")
if ($sys -eq "1") {
    Write-Host "OLLAMA_VULKAN=1 [System] - CORRECT" -ForegroundColor Green
} elseif ($user -eq "1") {
    Write-Host "OLLAMA_VULKAN=1 [User] - OK (system-level preferred)" -ForegroundColor Yellow
} else {
    Write-Host "OLLAMA_VULKAN not set - GPU will NOT be used!" -ForegroundColor Red
    Write-Host "Run 02_install_ollama.ps1 as Administrator"
}

Write-Host "`n--- Flash Attention env var ---"
$fa = [Environment]::GetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","Machine")
if ($fa -eq "1") {
    Write-Host "OLLAMA_FLASH_ATTENTION=1 [System] - CORRECT" -ForegroundColor Green
} else {
    Write-Host "OLLAMA_FLASH_ATTENTION not set - run 02_install_ollama.ps1" -ForegroundColor Yellow
}
