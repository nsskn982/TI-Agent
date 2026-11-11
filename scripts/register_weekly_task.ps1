<#
.SYNOPSIS
    Registers the TI Agent weekly run (M8) in Windows Task Scheduler.
.DESCRIPTION
    Runs `python -m orchestration.weekly_run` from the repo's .venv every week,
    logging to logs\weekly_run.log. Ollama must be installed (its tray app starts
    the server at logon). The task runs only while you are logged on, because it
    needs your user environment (.env, Ollama settings).
.EXAMPLE
    .\scripts\register_weekly_task.ps1
    .\scripts\register_weekly_task.ps1 -Day Sunday -Time 10:00
    .\scripts\register_weekly_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$Day = "Saturday",
    [string]$Time = "09:00",
    [string]$TaskName = "TI-Agent weekly run",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'."
    return
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No .venv found. Run .\scripts\setup.ps1 first." }
New-Item -ItemType Directory -Force (Join-Path $Root "logs") | Out-Null

# cmd /c gives us output redirection into a log file.
$command = "`"$python`" -m orchestration.weekly_run >> logs\weekly_run.log 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "TI Agent: weekly suggestions via the local LLM" -Force | Out-Null

Write-Host "Registered '$TaskName': every $Day at $Time (missed runs start when the PC is next on)."
Write-Host "Run it now with:  Start-ScheduledTask -TaskName '$TaskName'"
