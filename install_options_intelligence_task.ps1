$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bat = Join-Path $ProjectRoot "run_options_intelligence_collector.bat"
$TaskName = "APlusOptionsIntelligenceCollector"

if (-not (Test-Path $Bat)) {
    throw "Missing launcher: $Bat"
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c \`"$Bat\`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType InteractiveToken -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started: $TaskName"
Write-Host "The runtime waits outside 09:15-15:30 IST, runs weekdays only, reconnects after runtime failures, and stops after 15:30."
