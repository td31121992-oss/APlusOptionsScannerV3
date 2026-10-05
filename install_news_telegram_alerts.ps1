param(
    [string]$ProjectRoot = "",
    [switch]$InstallTask
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Worker = Join-Path $ProjectRoot "news_telegram_alerts.py"
if (-not (Test-Path $Python)) { throw "Missing project Python: $Python" }
if (-not (Test-Path $Worker)) { throw "Missing worker: $Worker" }
& $Python -m py_compile $Worker
if ($LASTEXITCODE -ne 0) { throw "Python syntax validation failed." }
if ($InstallTask) {
    $name = "APlus_News_Telegram_Alerts"
    $backup = Join-Path $ProjectRoot ("data\backups\scheduled_tasks\news_telegram_{0}" -f (Get-Date -Format yyyyMMdd_HHmmss))
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    try { Export-ScheduledTask -TaskName $name -ErrorAction Stop | Set-Content (Join-Path $backup "$name.xml") -Encoding UTF8 } catch {}
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $action = New-ScheduledTaskAction -Execute $Python -Argument ('"' + $Worker + '"') -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 7)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "INSTALLED: $name" -ForegroundColor Green
} else {
    Write-Host "Validation OK. Use -InstallTask to register the unattended Telegram news worker."
}
