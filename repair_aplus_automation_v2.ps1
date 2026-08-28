param([string]$ProjectRoot="C:\\Users\\Darpan.bobhate\\Desktop\\APlusOptionsScannerV3")
$ErrorActionPreference="Stop"
$wrapper=Join-Path $ProjectRoot "aplus_market_runtime_wrapper_v2.ps1"
if(-not (Test-Path $wrapper)){throw "Wrapper missing: $wrapper"}

$arg='-NoProfile -ExecutionPolicy Bypass -File "{0}" -ProjectRoot "{1}"' -f $wrapper,$ProjectRoot
$action=New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ProjectRoot

foreach($name in @("APlus_Full_AutoStart","APlus_Runtime_Watchdog")){
  $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if(-not $task){throw "Scheduled task not found: $name"}
  Set-ScheduledTask -TaskName $name -Action $action | Out-Null
  Write-Host "PASS repaired action: $name"
}

Write-Host ""
Write-Host "ACTIONS AFTER REPAIR:"
foreach($name in @("APlus_Full_AutoStart","APlus_Runtime_Watchdog")){
  Write-Host ("--- "+$name+" ---")
  (Get-ScheduledTask -TaskName $name).Actions | Format-List Execute,Arguments,WorkingDirectory
}

Write-Host ""
Write-Host "RUN WRAPPER NOW..."
& $wrapper -ProjectRoot $ProjectRoot
