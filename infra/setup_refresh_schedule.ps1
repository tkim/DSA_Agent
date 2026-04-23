#Requires -Version 5.1
<#
.SYNOPSIS
    Register a weekly Windows Scheduled Task that keeps the DSA Agent
    RAG corpus up to date by running rag/refresher.py every Monday at 03:00.

.DESCRIPTION
    The task runs silently in the background.  It checks each doc source's
    latest GitHub commit SHA against the stored version fingerprint.
    If anything changed it re-downloads and re-ingests only that platform.
    If the machine is offline the script exits cleanly — no corpus is touched.

    Run this script ONCE after initial setup.  Re-run to update the task
    if you change the repo path or Python venv location.

.NOTES
    Does NOT require Administrator rights — the task runs as the current user
    using the 'Interactive' logon type.  This means the task only fires when
    you are logged in, which is fine for a developer workstation.
    Logs are written to: <repo>\rag\refresh.log
#>

$ErrorActionPreference = 'Stop'   # surface failures — never claim false success

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
$RepoRoot  = Split-Path -Parent $PSScriptRoot          # parent of infra\
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script    = Join-Path $RepoRoot "rag\refresher.py"
$LogFile   = Join-Path $RepoRoot "rag\refresh.log"
$TaskName  = "DSA-Agent-RAG-Refresh"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python venv not found at $PythonExe`nRun: py -3.11 -m venv .venv && .\.venv\Scripts\pip install -e ."
    exit 1
}
if (-not (Test-Path $Script)) {
    Write-Error "refresher.py not found at $Script"
    exit 1
}

Write-Host "Repository root : $RepoRoot"   -ForegroundColor Cyan
Write-Host "Python          : $PythonExe"  -ForegroundColor Cyan
Write-Host "Refresher script: $Script"     -ForegroundColor Cyan
Write-Host "Log file        : $LogFile"    -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Build the action — run python with logging redirected to refresh.log
# ---------------------------------------------------------------------------
# PowerShell's -WindowStyle Hidden keeps it fully background.
# Stdout and stderr are appended to refresh.log with a datestamp header.
$ActionCmd = "powershell.exe"
$ActionArgs = @"
-NonInteractive -WindowStyle Hidden -Command "
    Add-Content -Path '$LogFile' -Value ('`n=== Refresh started ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ===');
    & '$PythonExe' '$Script' 2>&1 | Add-Content -Path '$LogFile'
"
"@

$Action  = New-ScheduledTaskAction -Execute $ActionCmd -Argument $ActionArgs -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "03:00"

# Run whether or not the user is logged in; do NOT store password.
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit    (New-TimeSpan -Hours 1)  `
    -StartWhenAvailable                              `
    -WakeToRun:$false                                `
    -MultipleInstances     IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId    "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel  Limited

# ---------------------------------------------------------------------------
# Register (or update) the task
# ---------------------------------------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Updating existing task '$TaskName'..." -ForegroundColor Yellow
    Set-ScheduledTask -TaskName $TaskName `
        -Action $Action -Trigger $Trigger `
        -Settings $Settings -Principal $Principal | Out-Null
} else {
    Write-Host "Registering new task '$TaskName'..." -ForegroundColor Green
    Register-ScheduledTask `
        -TaskName  $TaskName  `
        -Action    $Action    `
        -Trigger   $Trigger   `
        -Settings  $Settings  `
        -Principal $Principal `
        -Description "Weekly RAG corpus refresh for DSA Agent (SHA-based, offline-safe)" | Out-Null
}

Write-Host ""
Write-Host "Task registered successfully." -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Task name  : $($task.TaskName)"
Write-Host "State      : $($task.State)"
$nextRun = (Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime
Write-Host "Next run   : $nextRun"
Write-Host ""

# ---------------------------------------------------------------------------
# Offer an immediate test run
# ---------------------------------------------------------------------------
$run = Read-Host "Run --check-only now to verify GitHub connectivity? (y/N)"
if ($run -match '^[Yy]') {
    Write-Host "`nRunning check-only..." -ForegroundColor Cyan
    & $PythonExe $Script --check-only
}

Write-Host @"

Done.  To manage the task:
  Check status : Get-ScheduledTaskInfo -TaskName '$TaskName'
  Run manually : Start-ScheduledTask  -TaskName '$TaskName'
  Remove       : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false
  View log     : Get-Content '$LogFile' -Tail 50
"@ -ForegroundColor Yellow
