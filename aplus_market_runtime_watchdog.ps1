param(
    [string]$ProjectRoot = "C:\Users\Darpan.bobhate\Desktop\APlusOptionsScannerV3"
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

$Now = Get-Date
$Today = $Now.ToString("yyyy-MM-dd")
$Hm = [int]$Now.ToString("HHmm")

function Get-PythonProc([string]$pattern) {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(.exe)?$' -and $_.CommandLine -match $pattern
    })
}

function Ensure-OneProcess(
    [string]$Name,
    [string]$Pattern,
    [string]$Command,
    [int]$NotBefore = 0,
    [int]$NotAfter = 2359
) {
    $hm = [int](Get-Date).ToString("HHmm")
    if ($hm -lt $NotBefore -or $hm -gt $NotAfter) {
        Write-Host "SKIP $Name outside window"
        return
    }

    $p = Get-PythonProc $Pattern
    if ($p.Count -gt 1) {
        Write-Host "WARN $Name duplicate count=$($p.Count) - keeping first, stopping extras"
        $keep = $p | Select-Object -First 1
        $p | Where-Object {$_.ProcessId -ne $keep.ProcessId} | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
        $p = Get-PythonProc $Pattern
    }

    if ($p.Count -eq 0) {
        Write-Host "START $Name"
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "cd /d `"$ProjectRoot`" && $Command" -WindowStyle Minimized
        Start-Sleep -Seconds 3
        $p = Get-PythonProc $Pattern
    } else {
        Write-Host "PASS $Name already running PID=$($p[0].ProcessId)"
    }

    Write-Host "$Name COUNT=$($p.Count)"
}

# 1) Safety agent first, so portfolio_state.json rolls over before scanner evaluates it.
Ensure-OneProcess `
    -Name "PAPER Safety Evidence Agent" `
    -Pattern "paper_safety_evidence_agent\.py" `
    -Command "python paper_safety_evidence_agent.py" `
    -NotBefore 905 -NotAfter 1535

# Wait for today's PAPER state to appear.
if ($Hm -ge 905 -and $Hm -le 1535) {
    $state = Join-Path $ProjectRoot "data\portfolio_state.json"
    $deadline = (Get-Date).AddSeconds(20)
    $stateOk = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $state) {
            try {
                $j = Get-Content $state -Raw | ConvertFrom-Json
                if ([string]$j.date -eq $Today) {
                    $stateOk = $true
                    Write-Host "PASS portfolio_state date=$($j.date) pnl=$($j.realized_pnl_today) losses=$($j.consecutive_losses)"
                    break
                }
            } catch {}
        }
        Start-Sleep -Seconds 2
    }

    if (-not $stateOk) {
        Write-Host "BLOCK scanner auto-start: portfolio_state.json not refreshed to $Today"
    } else {
        # 2) Main scanner only after state is correct.
        Ensure-OneProcess `
            -Name "APlus Intraday Scanner" `
            -Pattern "main\.py\s+--intraday-movement" `
            -Command "python main.py --intraday-movement" `
            -NotBefore 910 -NotAfter 1530
    }
}

# 3) Dashboard V2 is local/file-based and may run alongside scanner.
if (Test-Path (Join-Path $ProjectRoot "aplus_dashboard_v2.py")) {
    Ensure-OneProcess `
        -Name "APlus Dashboard V2" `
        -Pattern "aplus_dashboard_v2\.py" `
        -Command "python aplus_dashboard_v2.py" `
        -NotBefore 910 -NotAfter 1600
}

# 4) Campaign shadow - start only if file exists. It is SHADOW ONLY.
if (Test-Path (Join-Path $ProjectRoot "movement_campaign_intelligence_v1_shadow.py")) {
    Ensure-OneProcess `
        -Name "Campaign Intelligence Shadow" `
        -Pattern "movement_campaign_intelligence_v1_shadow\.py" `
        -Command "python movement_campaign_intelligence_v1_shadow.py --interval 30" `
        -NotBefore 914 -NotAfter 1535
}

# Write automation health snapshot.
$scanner = Get-PythonProc "main\.py\s+--intraday-movement"
$safety  = Get-PythonProc "paper_safety_evidence_agent\.py"
$dash    = Get-PythonProc "aplus_dashboard_v2\.py"
$camp    = Get-PythonProc "movement_campaign_intelligence_v1_shadow\.py"

$health = [ordered]@{
    as_of = (Get-Date).ToString("o")
    date = $Today
    scanner_count = $scanner.Count
    safety_agent_count = $safety.Count
    dashboard_v2_count = $dash.Count
    campaign_shadow_count = $camp.Count
}
$healthPath = Join-Path $ProjectRoot "data\aplus_automation_health.json"
$health | ConvertTo-Json | Set-Content -Path $healthPath -Encoding UTF8
Write-Host ($health | ConvertTo-Json -Compress)
