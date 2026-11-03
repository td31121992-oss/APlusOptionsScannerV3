# Controlled scanner restart. Run this from an ELEVATED (Administrator) PowerShell: the scanner runs in an elevated context,
# so a normal session can neither see nor stop it.
#
#   powershell -ExecutionPolicy Bypass -File .\restart_scanner_elevated.ps1
#
# It stops exactly ONE scanner (a launcher + its child interpreter) whose command line is "<project>\main.py --intraday-movement", waits for it to exit, then starts
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
# A venv python.exe is a launcher that starts the real interpreter, so one scanner shows up as a parent + child pair.
# Count a scanner only once: the processes whose parent is not itself one of the matches.
$ids = @($p | ForEach-Object { [int]$_.ProcessId })
$roots = @($p | Where-Object { $ids -notcontains [int]$_.ParentProcessId })
if ($roots.Count -ne 1) {
    Write-Host "Found $($roots.Count) separate scanner(s) ($($p.Count) processes); expected exactly 1. Nothing was stopped." -ForegroundColor Yellow
    $p | ForEach-Object { Write-Host ("  PID {0} (parent {1}): {2}" -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine) }
    exit 2
}
Write-Host ("Stopping scanner: launcher PID {0} and {1} child process(es) ..." -f $roots[0].ProcessId, ($p.Count - 1))
# children first, then the launcher
foreach ($proc in @($p | Where-Object { [int]$_.ProcessId -ne [int]$roots[0].ProcessId })) { Stop-Process -Id ([int]$proc.ProcessId) -ErrorAction SilentlyContinue }
Stop-Process -Id ([int]$roots[0].ProcessId) -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
if ((ScannerProcesses).Count -gt 0) { throw "Scanner is still running; launcher NOT started." }

$launcher = Join-Path $ProjectRoot "run_intraday_movement.bat"
if (-not (Test-Path $launcher)) { throw "Launcher missing: $launcher" }
Write-Host "Starting scanner ..."
Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "call `"$launcher`"") -WorkingDirectory $ProjectRoot -WindowStyle Minimized
Start-Sleep -Seconds 25
if ((ScannerProcesses).Count -ge 1) { Write-Host "Scanner restarted." -ForegroundColor Green } else { Write-Host "Scanner is not visible yet - check data\reports\intraday_movement_latest.json in a minute." -ForegroundColor Yellow }
