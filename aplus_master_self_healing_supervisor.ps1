param(
    [string]$ProjectRoot = "C:\Users\Aplus\Desktop\APlusOptionsScannerV3",
    [switch]$RunOnce
)

$ErrorActionPreference = "Continue"

$LogDir = Join-Path $ProjectRoot "data\logs"
$HealthPath = Join-Path $ProjectRoot "data\aplus_master_health.json"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScannerLauncher = Join-Path $ProjectRoot "aplus_auto_start.bat"
$Preflight = Join-Path $ProjectRoot "aplus_preflight_check.py"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$mutexName = "Global\APlusOptionsScannerV3_MasterSelfHealingV4"
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdNew)

if (-not $createdNew) {
    exit 0
}

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff"), $Message
    Add-Content -Path (Join-Path $LogDir "aplus_master_self_healing.log") -Value $line
}

function Test-MarketSession {
    $now = Get-Date

    if ($now.DayOfWeek -eq "Saturday" -or $now.DayOfWeek -eq "Sunday") {
        return $false
    }

    $t = $now.TimeOfDay

    return (
        $t -ge [TimeSpan]::Parse("09:15:00") -and
        $t -le [TimeSpan]::Parse("15:30:00")
    )
}

function Get-ScannerProcesses {
    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine -match [regex]::Escape($ProjectRoot) -and
            $_.CommandLine -match "main\.py\s+--intraday-movement"
        }
    )
}

function Test-Dhan {
    if (-not (Test-Path $Python)) {
        return $false
    }

    try {
        & $Python $Preflight *> (Join-Path $LogDir "aplus_master_preflight.log")
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Test-ReportFresh {
    $report = Join-Path $ProjectRoot "data\reports\intraday_movement_latest.json"

    if (-not (Test-Path $report)) {
        return $false
    }

    try {
        return (((Get-Date) - (Get-Item $report).LastWriteTime).TotalSeconds -le 180)
    }
    catch {
        return $false
    }
}

Write-Log "============================================================"
Write-Log "APlus Master Self-Healing Supervisor V4 START"
Write-Log "Trading engine untouched"
Write-Log "No token generation/replacement"
Write-Log "No blind process termination"
Write-Log "No forced paper-trade close"

do {

    $now = Get-Date
    $market = Test-MarketSession
    $dhan = Test-Dhan
    $scanner = @(Get-ScannerProcesses)
    $reportFresh = Test-ReportFresh

    $scannerCount = $scanner.Count

    $scannerHealthy = (
        $scannerCount -eq 1 -and
        ($reportFresh -or -not $market)
    )

    if ($market -and $dhan -and -not $scannerHealthy) {

        Write-Log "SCANNER RECOVERY ELIGIBLE: scannerCount=$scannerCount reportFresh=$reportFresh"

        if (Test-Path $ScannerLauncher) {

            try {

                Start-Process `
                    -FilePath $ScannerLauncher `
                    -WorkingDirectory $ProjectRoot `
                    -WindowStyle Minimized

                Write-Log "RECOVERY START: existing guarded launcher invoked"

            }
            catch {

                Write-Log "RECOVERY ERROR: $($_.Exception.Message)"

            }

        }
        else {

            Write-Log "RECOVERY BLOCKED: aplus_auto_start.bat missing"

        }

    }
    elseif ($scannerCount -eq 1) {

        Write-Log "SCANNER HEALTHY: one scanner process detected"

    }
    elseif ($scannerCount -gt 1) {

        Write-Log "SAFETY: multiple scanner processes detected; NO PROCESS TERMINATION"

    }
    elseif (-not $dhan) {

        Write-Log "SCANNER RECOVERY BLOCKED: Dhan preflight failed"

    }

    $health = [ordered]@{
        service = "APlus Master Self-Healing Supervisor"
        version = 4
        updated_at = $now.ToString("o")
        market_session = $market
        dhan_ready = $dhan
        scanner_count = $scannerCount
        scanner_process_healthy = $scannerHealthy
        report_fresh = $reportFresh
        pnl_policy = "DELEGATED_TO_PAPER_TRADE_JOURNAL"
        safety_policy = "NO_TOKEN_GENERATION;NO_TRADING_ENGINE_MODIFICATION;NO_BLIND_PROCESS_KILL;NO_FABRICATED_PNL;NO_FORCED_CLOSE"
    }

    $health |
        ConvertTo-Json -Depth 8 |
        Set-Content -Path $HealthPath -Encoding utf8

    if ($RunOnce) {
        break
    }

    Start-Sleep -Seconds 30

}
while ($true)

Write-Log "APlus Master Self-Healing Supervisor V4 EXIT"
