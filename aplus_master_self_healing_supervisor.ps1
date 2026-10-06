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

function Select-RootScannerProcesses($Processes) {
    # A venv python.exe launcher spawns the real interpreter as a child with the
    # same command line, so one scanner appears as two processes. Count only
    # processes whose parent is not itself a matching scanner process.
    $list = @($Processes)
    $ids = @($list | ForEach-Object { [int]$_.ProcessId })
    @($list | Where-Object { $ids -notcontains [int]$_.ParentProcessId })
}

function Get-ScannerProcesses {
    $found = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine -match [regex]::Escape($ProjectRoot) -and
            $_.CommandLine -match "main\.py\s+--intraday-movement"
        }
    )
    Select-RootScannerProcesses $found
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

$RecoveryCooldownSeconds = 180
$lastRecovery = [datetime]::MinValue
$dhan = $null

do {

    $now = Get-Date
    $market = Test-MarketSession
    $scanner = @(Get-ScannerProcesses)
    $reportFresh = Test-ReportFresh

    $scannerCount = $scanner.Count

    $scannerHealthy = (
        $scannerCount -eq 1 -and
        ($reportFresh -or -not $market)
    )

    # Relaunch only when NO scanner is running. Two or more processes, or a
    # stale report with one scanner, are logged but never acted on blindly.
    if ($market -and $scannerCount -eq 0) {

        if (((Get-Date) - $lastRecovery).TotalSeconds -lt $RecoveryCooldownSeconds) {

            Write-Log "SCANNER RECOVERY WAIT: cooldown after previous launch"

        }
        else {

            # Preflight (a Dhan API call) runs only when a relaunch is needed.
            $dhan = Test-Dhan

            if (-not $dhan) {

                Write-Log "SCANNER RECOVERY BLOCKED: Dhan preflight failed"

            }
            elseif (Test-Path $ScannerLauncher) {

                Write-Log "SCANNER RECOVERY ELIGIBLE: no scanner process detected"

                try {

                    Start-Process `
                        -FilePath $ScannerLauncher `
                        -WorkingDirectory $ProjectRoot `
                        -WindowStyle Minimized

                    $lastRecovery = Get-Date
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

    }
    elseif ($scannerCount -eq 1 -and $market -and -not $reportFresh) {

        Write-Log "WARN: one scanner running but report is stale (>180s); no action taken"

    }
    elseif ($scannerCount -eq 1) {

        Write-Log "SCANNER HEALTHY: one scanner process detected"

    }
    elseif ($scannerCount -gt 1) {

        Write-Log "SAFETY: multiple scanner processes detected (count=$scannerCount); NO PROCESS TERMINATION, NO RELAUNCH"

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
