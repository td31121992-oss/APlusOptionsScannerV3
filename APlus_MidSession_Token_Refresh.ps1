param(
    [string]$ProjectRoot = "",
    [switch]$Force
)

$ErrorActionPreference = "Continue"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$CAlphaRoot = Join-Path (Split-Path -Parent $ProjectRoot) "CAlphaTrader"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TokenScript = Join-Path $CAlphaRoot "tools\dhan_auto_token.py"
$LogDir = Join-Path $ProjectRoot "data\startup"
$LogPath = Join-Path $LogDir "APlus_MidSession_Token_Refresh.log"
$LastPath = Join-Path $LogDir "midsession_refresh_last.txt"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log([string]$m) {
    Add-Content -LiteralPath $LogPath -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding UTF8
}

function ScannerProcesses {
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine -match "main\.py" -and
        $_.CommandLine -match "--intraday-movement" -and
        $_.CommandLine -match [regex]::Escape($ProjectRoot)
    })
}

if (-not $Force) {
    $n = Get-Date
    if ($n.DayOfWeek -eq [DayOfWeek]::Saturday -or $n.DayOfWeek -eq [DayOfWeek]::Sunday) { exit 0 }
    $hm = [int]$n.ToString("HHmm")
    if ($hm -lt 1430 -or $hm -gt 1455) {
        Log "SKIP outside safe mid-session refresh window."
        exit 0
    }
}

if (-not (Test-Path $Python)) { Log "ERROR project Python missing: $Python"; exit 13 }
if (-not (Test-Path $TokenScript)) { Log "ERROR CAlphaTrader token generator missing: $TokenScript"; exit 14 }

Log "Refreshing Dhan token ahead of known mid-session expiry."

$oldEnv = Join-Path $CAlphaRoot ".env"
$oldStamp = if (Test-Path $oldEnv) { (Get-Item $oldEnv).LastWriteTimeUtc } else { [datetime]::MinValue }
$out = & $Python $TokenScript 2>&1
$exit = $LASTEXITCODE
$out | Set-Content -LiteralPath $LastPath -Encoding UTF8

if ($exit -ne 0 -or -not (($out -join [Environment]::NewLine) -match "DHAN_TOKEN_REFRESH_OK")) {
    Log "ERROR token refresh failed exit=$exit. Scanner was NOT restarted."
    exit 20
}
if (-not (Test-Path $oldEnv) -or (Get-Item $oldEnv).LastWriteTimeUtc -le $oldStamp) {
    Log "ERROR token generator reported success but CAlphaTrader .env timestamp did not advance. Scanner was NOT restarted."
    exit 21
}

Log "Token refresh OK. Re-validating market-data authorization (one read-only quote)."
$validator = Join-Path $ProjectRoot "validate_market_data_authorization.py"
if (Test-Path $validator) {
    $vOut = & $Python $validator 2>&1
    if ($LASTEXITCODE -eq 0) {
        Log "PASS authorization latch revalidated: $($vOut -join ' ')"
    } else {
        Log "WARN authorization revalidation did not pass: $($vOut -join ' '). Existing latch state left unchanged."
    }
}
Log "Checking scanner before controlled restart."
$p = ScannerProcesses

if ($p.Count -eq 0) {
    Log "PASS token refreshed; scanner not running, so no restart was attempted."
    exit 0
}
if ($p.Count -gt 1) {
    Log "WARN multiple exact scanner processes detected count=$($p.Count); NO process termination performed."
    exit 22
}

$pid = [int]$p[0].ProcessId
try {
    Stop-Process -Id $pid -ErrorAction Stop
    Log "Stopped exactly identified scanner PID=$pid after successful token validation."
} catch {
    Log "ERROR unable to stop exact scanner PID=$pid : $($_.Exception.Message)"
    exit 23
}

Start-Sleep -Seconds 3
$remaining = ScannerProcesses
if ($remaining.Count -gt 0) {
    Log "ERROR scanner process remained after controlled stop; launcher NOT started."
    exit 24
}

$launcher = Join-Path $ProjectRoot "run_intraday_movement.bat"
if (-not (Test-Path $launcher)) { Log "ERROR launcher missing: $launcher"; exit 25 }

Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "call '$launcher'") -WorkingDirectory $ProjectRoot -WindowStyle Minimized
Start-Sleep -Seconds 20

if ((ScannerProcesses).Count -gt 0) {
    Log "PASS: scanner restarted with fresh token."
    exit 0
}

Log "ERROR: scanner did not remain running after token refresh restart."
exit 26
