param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Continue"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "data\logs"
$HealthDir = Join-Path $ProjectRoot "data"
$LogPath = Join-Path $LogDir "aplus_24x7_supervisor.log"
$HealthPath = Join-Path $HealthDir "aplus_24x7_health.json"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\options_intelligence") | Out-Null

$script:Mutex = New-Object System.Threading.Mutex($false, "Global\APlusOptionsScannerV3_24x7_Supervisor")
if (-not $script:Mutex.WaitOne(0, $false)) {
    exit 0
}

$script:LastPreflight = $false
$script:LastPreflightAt = $null
$script:LastWatchdogAt = $null
$script:LastOptionsTaskStartAt = $null
$script:Cycle = 0
$script:StartedAt = (Get-Date).ToString("o")

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff"), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Get-PythonProcesses([string]$Pattern) {
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
        $_.CommandLine -and
        $_.CommandLine -match $Pattern
    })
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 2500) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($ok -and $client.Connected) {
            $client.EndConnect($async)
            $client.Close()
            return $true
        }
        $client.Close()
    } catch {}
    return $false
}

function Test-DhanReadiness {
    $preflight = Join-Path $ProjectRoot "aplus_preflight_check.py"
    if (-not (Test-TcpPort "api.dhan.co" 443 2500)) {
        return $false
    }

    if (Test-Path $preflight) {
        try {
            & $script:Python $preflight *> (Join-Path $LogDir "aplus_preflight_24x7.log")
            return ($LASTEXITCODE -eq 0)
        } catch {
            return $false
        }
    }

    try {
        & $script:Python "-c" "from config import CONFIG; print('APlus Dhan preflight PASS')" *> (Join-Path $LogDir "aplus_preflight_24x7.log")
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-MarketSession {
    $now = Get-Date
    if ($now.DayOfWeek -eq [DayOfWeek]::Saturday -or $now.DayOfWeek -eq [DayOfWeek]::Sunday) {
        return $false
    }
    $hm = [int]$now.ToString("HHmm")
    return ($hm -ge 915 -and $hm -le 1530)
}

function Ensure-Process(
    [string]$Name,
    [string]$Pattern,
    [string]$Executable,
    [string[]]$Arguments
) {
    $p = Get-PythonProcesses $Pattern

    # Never kill a process from the top-level supervisor. Multiple matches can
    # be launcher/child trees, and force-killing trading-related runtimes is
    # unsafe. Deduplication is handled by authoritative launcher/health evidence.
    if ($p.Count -gt 1) {
        Write-Log "DUPLICATE DETECTED $Name count=$($p.Count); no process termination performed"
    }

    if ($p.Count -eq 0) {
        if (-not (Test-Path $Executable)) {
            Write-Log "MISSING $Name executable=$Executable"
            return 0
        }

        try {
            $argLine = ($Arguments | ForEach-Object {
                if ($_ -match "\s") { '"' + $_.Replace('"','\"') + '"' } else { $_ }
            }) -join " "
            Start-Process -FilePath $Executable -ArgumentList $argLine -WorkingDirectory $ProjectRoot -WindowStyle Minimized | Out-Null
            Write-Log "START $Name"
            Start-Sleep -Seconds 3
            $p = Get-PythonProcesses $Pattern
        } catch {
            Write-Log "ERROR starting $Name : $($_.Exception.Message)"
        }
    }

    if ($p.Count -gt 0) {
        Write-Log "HEALTH $Name count=$($p.Count) pid=$($p[0].ProcessId)"
    } else {
        Write-Log "DOWN $Name"
    }

    return $p.Count
}

function Ensure-OptionsTask {
    $taskName = "APlusOptionsIntelligenceCollector"
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ((Test-MarketSession) -and $script:LastPreflight) {
            if ($task.State -ne "Running") {
                Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
                $script:LastOptionsTaskStartAt = (Get-Date).ToString("o")
                Write-Log "START scheduled task $taskName"
            }
        }
        return (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue).State
    } catch {
        Write-Log "OPTIONS_TASK missing/unavailable: $($_.Exception.Message)"
        return "MISSING"
    }
}

function Invoke-MarketWatchdog {
    $watchdog = Join-Path $ProjectRoot "aplus_market_runtime_watchdog.ps1"
    if (-not (Test-Path $watchdog)) {
        Write-Log "MISSING market runtime watchdog"
        return
    }

    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $watchdog -ProjectRoot $ProjectRoot *> (Join-Path $LogDir "aplus_market_runtime_watchdog_24x7.log")
        $script:LastWatchdogAt = (Get-Date).ToString("o")
        Write-Log "MARKET watchdog completed exit=$LASTEXITCODE"
    } catch {
        Write-Log "ERROR market watchdog: $($_.Exception.Message)"
    }
}

try {
    $script:Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    Write-Log "============================================================"
    Write-Log "APlus 24x7 Reliability Supervisor START"
    Write-Log "ProjectRoot=$ProjectRoot"
    Write-Log "Python=$script:Python"
    Write-Log "Core trading engine is not modified by this supervisor."

    if (-not (Test-Path $script:Python)) {
        Write-Log "FATAL project venv Python missing"
        exit 13
    }

    while ($true) {
        $script:Cycle++
        $now = Get-Date
        $market = Test-MarketSession

        $liveDashboard = Ensure-Process -Name "APlus Live Dashboard" -Pattern "aplus_live_pnl_dashboard\.py" -Executable $script:Python -Arguments @((Join-Path $ProjectRoot "aplus_live_pnl_dashboard.py"))

        $dashboardV2 = 0
        $dashV2Path = Join-Path $ProjectRoot "aplus_dashboard_v2.py"
        if (Test-Path $dashV2Path) {
            $dashboardV2 = Ensure-Process -Name "APlus Dashboard V2" -Pattern "aplus_dashboard_v2\.py" -Executable $script:Python -Arguments @($dashV2Path)
        }

        $script:LastPreflightAt = $now.ToString("o")
        if ($market) {
            $script:LastPreflight = Test-DhanReadiness
            if ($script:LastPreflight) {
                Write-Log "Dhan readiness=PASS"
            } else {
                Write-Log "Dhan readiness=WAITING; scanner will not be force-started"
            }
        } else {
            $script:LastPreflight = $false
        }

        $optionsState = Ensure-OptionsTask

        # Authoritative scanner health gate: a live scanner process plus a fresh
        # intraday report means the scanner is healthy. Do not invoke another
        # launcher merely because process detection is transient.
        $scanner = Get-PythonProcesses "main\.py["']?\s+--intraday-movement"
        $reportHealthy = $false
        try {
            $reportPath = Join-Path $ProjectRoot "data\reports\intraday_movement_latest.json"
            if (Test-Path $reportPath) {
                $age = ((Get-Date) - (Get-Item $reportPath).LastWriteTime).TotalSeconds
                $reportHealthy = ($age -ge 0 -and $age -le 180)
            }
        } catch {}
        $scannerHealthy = ($scanner.Count -gt 0 -and $reportHealthy)
        if ($market -and $script:LastPreflight -and -not $scannerHealthy) {
            Invoke-MarketWatchdog
        } elseif ($market -and $script:LastPreflight -and $scannerHealthy) {
            Write-Log "SKIP market watchdog: scanner healthy process=$($scanner.Count) fresh_report=$reportHealthy"
        }

        $safety = Get-PythonProcesses "paper_safety_evidence_agent\.py"
        $campaign = Get-PythonProcesses "movement_campaign_intelligence_v1_shadow\.py"
        $optionsRuntime = Get-PythonProcesses "options_intelligence_runtime\.py"

        $health = [ordered]@{
            service = "APlus 24x7 Reliability Supervisor"
            version = 2
            read_only_supervisor = $true
            trading_engine_untouched = $true
            updated_at = $now.ToString("o")
            supervisor_started_at = $script:StartedAt
            cycle = $script:Cycle
            market_session = $market
            network_dhan_ready = $script:LastPreflight
            project_root = $ProjectRoot
            scanner_count = $scanner.Count
            scanner_process_detected = ($scanner.Count -gt 0)
            scanner_report_fresh = $reportHealthy
            scanner_health = $(if ($scannerHealthy) { "HEALTHY" } elseif ($scanner.Count -gt 0) { "PROCESS_ONLY" } else { "DOWN" })
            safety_agent_count = $safety.Count
            live_dashboard_count = $liveDashboard
            dashboard_v2_count = $dashboardV2
            campaign_shadow_count = $campaign.Count
            options_runtime_count = $optionsRuntime.Count
            options_task_state = $optionsState
            last_watchdog_at = $script:LastWatchdogAt
            last_options_task_start_at = $script:LastOptionsTaskStartAt
            token_policy = "APlus detects readiness only; CAlphaTrader remains authoritative for token generation."
        }

        try {
            $health | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $HealthPath -Encoding UTF8
        } catch {
            Write-Log "ERROR writing health: $($_.Exception.Message)"
        }

        if (($script:Cycle % 10) -eq 0) {
            Write-Log ("HEALTH " + ($health | ConvertTo-Json -Compress))
        }

        Start-Sleep -Seconds 30
    }
}
catch {
    Write-Log "SUPERVISOR FATAL: $($_.Exception.ToString())"
    throw
}
finally {
    try { $script:Mutex.ReleaseMutex() | Out-Null } catch {}
    try { $script:Mutex.Dispose() } catch {}
}

