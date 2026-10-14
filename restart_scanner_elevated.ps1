# Controlled scanner restart. Run this from an ELEVATED (Administrator) PowerShell: the scanner runs in an elevated context,
# so a normal session can neither see nor stop it.
#
#   powershell -ExecutionPolicy Bypass -File .\restart_scanner_elevated.ps1
#
# It stops exactly ONE process whose command line is "<project>\main.py --intraday-movement", waits for it to exit, then starts
# run_intraday_movement.bat. Open paper trades are kept in data\intraday_movement\paper_trade_journal.json and reload on start.
# Nothing is killed unless exactly one scanner process is found.
param([string]$ProjectRoot = "C:\Users\Aplus\Desktop\APlusOptionsScannerV3")
$ErrorActionPreference = "Stop"

function ScannerProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and $_.CommandLine -and
        $_.CommandLine -match "main\.py" -and $_.CommandLine -match "--intraday-movement" -and
        $_.CommandLine -match [regex]::Escape($ProjectRoot)
    })
}

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this from an elevated (Administrator) PowerShell."
}

$p = ScannerProcesses
if ($p.Count -ne 1) {
    Write-Host "Found $($p.Count) scanner process(es); expected exactly 1. Nothing was stopped." -ForegroundColor Yellow
    $p | ForEach-Object { Write-Host ("  PID {0}: {1}" -f $_.ProcessId, $_.CommandLine) }
    exit 2
}
$scannerPid = [int]$p[0].ProcessId
Write-Host "Stopping scanner PID $scannerPid ..."
Stop-Process -Id $scannerPid
Start-Sleep -Seconds 3
if ((ScannerProcesses).Count -gt 0) { throw "Scanner is still running; launcher NOT started." }

$launcher = Join-Path $ProjectRoot "run_intraday_movement.bat"
if (-not (Test-Path $launcher)) { throw "Launcher missing: $launcher" }
Write-Host "Starting scanner ..."
Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "call `"$launcher`"") -WorkingDirectory $ProjectRoot -WindowStyle Minimized
Start-Sleep -Seconds 25
if ((ScannerProcesses).Count -ge 1) { Write-Host "Scanner restarted." -ForegroundColor Green } else { Write-Host "Scanner is not visible yet - check data\reports\intraday_movement_latest.json in a minute." -ForegroundColor Yellow }
