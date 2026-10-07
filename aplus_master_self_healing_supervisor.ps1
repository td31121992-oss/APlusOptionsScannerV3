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

    # NSE holidays (data\safety\nse_holidays.csv). Fails open: a missing or
    # unreadable file is treated as a trading day.
    try {
        $holidayFile = Join-Path $ProjectRoot "data\safety\nse_holidays.csv"
        if (Test-Path $holidayFile) {
            $today = $now.ToString("yyyy-MM-dd")
            if (@(Import-Csv $holidayFile | Where-Object { $_.date -eq $today }).Count -gt 0) {
                return $false
            }
        }
    }
    catch { }

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

# 24x7 background services (news/announcements). Independent of market hours and of Dhan.
$Services = @(
    @{ Name = "Announcement service"; Script = "aplus_announcement_service.py" },
    @{ Name = "News collector";       Script = "aplus_overnight_intelligence.py" },
    @{ Name = "Order book recorder";  Script = "order_book_recorder.py" }
)
$ServiceLastStart = @{}
$ServiceCooldownSeconds = 300

function Ensure-Services {
    $pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $pythonw)) { $pythonw = $Python }
    foreach ($svc in $Services) {
        try {
            $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
                ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and $_.CommandLine -and
                $_.CommandLine -match [regex]::Escape($svc.Script)
            })
            if ($running.Count -gt 0) { continue }
            $last = $ServiceLastStart[$svc.Name]
            if ($last -and (((Get-Date) - $last).TotalSeconds -lt $ServiceCooldownSeconds)) { continue }
            $scriptPath = Join-Path $ProjectRoot $svc.Script
            if (-not (Test-Path $scriptPath)) { Write-Log "SERVICE MISSING: $($svc.Script)"; continue }
            Start-Process -FilePath $pythonw -ArgumentList "`"$scriptPath`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
            $ServiceLastStart[$svc.Name] = Get-Date
            Write-Log "SERVICE STARTED: $($svc.Name) ($($svc.Script))"
        }
        catch {
            Write-Log "SERVICE ERROR: $($svc.Name): $($_.Exception.Message)"
        }
    }
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
        return (((Get-Date) - (Get-Item $report).LastWriteTime).TotalSeconds -le 360)
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
    Ensure-Services
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
    # Liveness = the scanner's own report is fresh. A scanner started by an ELEVATED task (the 2-minute
    # watchdog) is invisible to this non-elevated supervisor (its command line cannot be read), so
    # process counting alone would start a duplicate that the watchdog then force-kills.
    if ($market -and $scannerCount -eq 0 -and $reportFresh) {

        Write-Log "SCANNER ALIVE: report is fresh (scanner process not visible - started by an elevated task); no action"

    }
    elseif ($market -and $scannerCount -eq 0) {

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
