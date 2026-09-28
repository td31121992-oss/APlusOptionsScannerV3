$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Supervisor = Join-Path $ProjectRoot "aplus_24x7_supervisor.ps1"
$TaskName = "APlus_24x7_Reliability_Supervisor"
$UserId = "$env:USERDOMAIN\\$env:USERNAME"

if (-not (Test-Path $Supervisor)) {
    throw "Missing supervisor: $Supervisor"
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$TaskRun = '"' + $PowerShell + '" -NoProfile -ExecutionPolicy Bypass -File "' + $Supervisor + '" -ProjectRoot "' + $ProjectRoot + '"'

schtasks.exe /Create /TN $TaskName /TR $TaskRun /SC ONLOGON /RU $UserId /IT /RL HIGHEST /F | Out-Host
schtasks.exe /Run /TN $TaskName | Out-Host

Write-Host "Installed and started: $TaskName"
Write-Host "Trigger: user logon"
Write-Host "Supervisor loop: every 30 seconds"
Write-Host "Task Scheduler recovery: task restart is handled by the Windows scheduler configuration after installation."
Write-Host "Core trading engine: untouched"
