param(
    [string]$ProjectRoot = "",
    [switch]$InstallTasks
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Missing project Python: $Python" }

$log = Join-Path $ProjectRoot "data\logs\24x7_install.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
function L([string]$m){ Add-Content $log ("[{0}] {1}" -f (Get-Date -Format o),$m) }

foreach($f in @("aplus_overnight_intelligence.py")){
    $p=Join-Path $ProjectRoot $f
    if(-not(Test-Path $p)){throw "Missing $p"}
    & $Python -m py_compile $p
    if($LASTEXITCODE -ne 0){throw "Python syntax failed: $p"}
}
$ps1=Join-Path $ProjectRoot "APlus_MidSession_Token_Refresh.ps1"
$sup=Join-Path $ProjectRoot "aplus_24x7_supervisor.ps1"
foreach($p in @($ps1,$sup)){ if(-not(Test-Path $p)){throw "Missing $p"} }

if($InstallTasks){
    $backup=Join-Path $ProjectRoot ("data\backups\scheduled_tasks\24x7_{0}" -f (Get-Date -Format yyyyMMdd_HHmmss))
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach($name in @("APlus_MidSession_Token_Refresh","APlus_24x7_Reliability_Supervisor","APlus_Overnight_Intelligence")){
        try {
            Export-ScheduledTask -TaskName $name -ErrorAction Stop | Set-Content (Join-Path $backup "$name.xml") -Encoding UTF8
            L "BACKUP $name"
        } catch { L "BACKUP_SKIP $name" }
    }

    # Preserve the current user's Windows credential-store context for CAlphaTrader.
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    $midAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoLogo -NoProfile -ExecutionPolicy Bypass -File '$ps1'"
    $midTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 14:40
    $midSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName "APlus_MidSession_Token_Refresh" -Action $midAction -Trigger $midTrigger -Settings $midSettings -Principal $principal -Force | Out-Null
    L "INSTALLED APlus_MidSession_Token_Refresh"

    $news = Join-Path $ProjectRoot "aplus_overnight_intelligence.py"
    $newsAction = New-ScheduledTaskAction -Execute $Python -Argument "'$news'" -WorkingDirectory $ProjectRoot
    $newsTrigger = New-ScheduledTaskTrigger -AtLogOn
    $newsSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 7)
    Register-ScheduledTask -TaskName "APlus_Overnight_Intelligence" -Action $newsAction -Trigger $newsTrigger -Settings $newsSettings -Principal $principal -Force | Out-Null
    L "INSTALLED APlus_Overnight_Intelligence"

    $supAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoLogo -NoProfile -ExecutionPolicy Bypass -File '$sup' -ProjectRoot '$ProjectRoot'"
    $supTrigger = New-ScheduledTaskTrigger -AtLogOn
    $supSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 7)
    Register-ScheduledTask -TaskName "APlus_24x7_Reliability_Supervisor" -Action $supAction -Trigger $supTrigger -Settings $supSettings -Principal $principal -Force | Out-Null
    L "INSTALLED APlus_24x7_Reliability_Supervisor"

    L "COMPLETE"
} else {
    Write-Host "Validation complete. Use -InstallTasks to update only the APlus 24x7 reliability tasks."
}
