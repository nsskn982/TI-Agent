<#
.SYNOPSIS
    Registers TI Agent's scheduled jobs in Windows Task Scheduler.
.DESCRIPTION
    TI-Agent daily refresh   weekdays           run_daily.cmd   (ingest + embed; new data only)
    TI-Agent weekly screen   Friday night       run_screen.cmd  (S&P 500 + MidCap 400, prune old data,
                                                                 score past views)
    TI-Agent weekly run      Saturday morning   run_weekly.cmd  (AI suggestions via local Ollama)
    TI-Agent weekly baseline Saturday, later    run_weekly.cmd --variant no_retrieval   (-WithBaseline:
                             the evaluation's no-search comparison; about 30 more GPU minutes a week)

    Each job starts Docker Desktop and the database container if needed. Tasks run only
    while you are logged on (they need your .env, Docker and Ollama), and missed runs start
    when the PC is next on. Times are local time; the defaults follow the US close in Europe.
.EXAMPLE
    .\scripts\register_tasks.ps1
    .\scripts\register_tasks.ps1 -DailyTime 23:00 -WeeklyDay Sunday
    .\scripts\register_tasks.ps1 -WithBaseline
    .\scripts\register_tasks.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$DailyTime = "23:45",
    [string]$ScreenTime = "01:30",          # Saturday 01:30, after Friday's daily refresh
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$WeeklyDay = "Saturday",
    [string]$WeeklyTime = "09:00",
    [string]$BaselineTime = "10:30",        # after the weekly run has freed the GPU
    [switch]$WithBaseline,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$names = "TI-Agent daily refresh", "TI-Agent weekly screen", "TI-Agent weekly run", "TI-Agent weekly baseline"

if ($Unregister) {
    foreach ($n in $names) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Host "Removed '$n'."
        }
    }
    return
}

if (-not (Test-Path (Join-Path $Root ".venv\Scripts\python.exe"))) { throw "No .venv found. Run .\scripts\setup.ps1 first." }
New-Item -ItemType Directory -Force (Join-Path $Root "logs") | Out-Null

function Register($name, $script, $trigger, $hours, $what, $extra = "") {
    # TI_NO_PAUSE: never wait for a key press when run by the scheduler.
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c set TI_NO_PAUSE=1&& `"$Root\$script`" $extra" `
        -WorkingDirectory $Root
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours $hours) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Description "TI Agent: $what" -Force | Out-Null
    Write-Host "Registered '$name'."
}

$weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
Register $names[0] "run_daily.cmd"  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $DailyTime) 2 `
    "daily refresh of prices, news, filings and macro (new data only)"
Register $names[1] "run_screen.cmd" (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $ScreenTime) 4 `
    "weekly S&P 500 + MidCap 400 screen and data retention"
Register $names[2] "run_weekly.cmd" (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $WeeklyTime) 3 `
    "weekly AI suggestions via the local LLM"
if ($WithBaseline) {
    Register $names[3] "run_weekly.cmd" (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $BaselineTime) 3 `
        "evaluation baseline: the same picks without document search (never published)" `
        "--variant no_retrieval --no-telegram"
}

Write-Host ""
Write-Host "Daily: weekdays $DailyTime. Screen: Saturday $ScreenTime. AI run: $WeeklyDay $WeeklyTime."
if ($WithBaseline) { Write-Host "Baseline (no search): $WeeklyDay $BaselineTime." }
Write-Host "Run one now with:  Start-ScheduledTask -TaskName '$($names[0])'"
Write-Host "Each run updates site-data\data.json for the app: push it to publish the new data."
