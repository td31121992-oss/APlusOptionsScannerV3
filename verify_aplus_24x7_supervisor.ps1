$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "APlus_24x7_Reliability_Supervisor"

Write-Host "=== APlus 24x7 Reliability Verification ==="
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host ""

Write-Host "--- Scheduled task ---"
Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Select-Object TaskName,State,TaskPath
Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue | Select-Object LastRunTime,LastTaskResult,NextRunTime,NumberOfMissedRuns

Write-Host ""
Write-Host "--- Supervisor process ---"
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -eq "powershell.exe" -or $_.Name -eq "pwsh.exe") -and $_.CommandLine -and $_.CommandLine -match "aplus_24x7_supervisor\.ps1"
} | Select-Object ProcessId,ParentProcessId,Name,CommandLine

Write-Host ""
Write-Host "--- Health evidence ---"
$health = Join-Path $ProjectRoot "data\aplus_24x7_health.json"
if (Test-Path $health) { Get-Content $health -Raw } else { Write-Host "Health file not present yet." }

Write-Host ""
Write-Host "--- Recent supervisor log ---"
$log = Join-Path $ProjectRoot "data\logs\aplus_24x7_supervisor.log"
if (Test-Path $log) { Get-Content $log -Tail 40 } else { Write-Host "Supervisor log not present yet." }

Write-Host ""
Write-Host "--- Managed processes ---"
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and (
        $_.CommandLine -match "main\.py\s+--intraday-movement" -or
        $_.CommandLine -match "paper_safety_evidence_agent\.py" -or
        $_.CommandLine -match "aplus_live_pnl_dashboard\.py" -or
        $_.CommandLine -match "aplus_dashboard_v2\.py" -or
        $_.CommandLine -match "options_intelligence_runtime\.py"
    )
} | Select-Object ProcessId,ParentProcessId,Name,CommandLine
