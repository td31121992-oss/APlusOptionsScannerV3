# APlusOptionsScannerV3 one-command shadow research runner
# Save to: tools\research\run_shadow_research.ps1
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\research\run_shadow_research.ps1"
# This runner uses an explicit allowlist. It does not run arbitrary discovered scripts.

$ErrorActionPreference = "Stop"
$Root = "C:\Users\Aplus\Desktop\APlusOptionsScannerV3"
$PythonCandidates = @(
    "C:\Users\Aplus\AppData\Local\Programs\Python\Python313\python.exe",
    (Join-Path $Root ".venv\Scripts\python.exe")
)
$Python = $PythonCandidates | Where-Object { $_ -and (Test-Path $_ -PathType Leaf) } | Select-Object -First 1
if (-not $Python) { throw "Python not found in expected locations." }
if (-not (Test-Path $Root -PathType Container)) { throw "Project root not found: $Root" }

$ResearchOut = Join-Path $Root "data\option_response_shadow_20261026"
$ReportDir = Join-Path $Root "reports\shadow_research_runner"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ReportPath = Join-Path $ReportDir "shadow_research_run_$Stamp.txt"
New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
"APLUS OPTIONS SCANNER — SHADOW RESEARCH RUN`r`nGenerated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')`r`nProject: $Root`r`nPython: $Python`r`nMode: READ-ONLY INPUTS / SHADOW RESEARCH OUTPUTS ONLY`r`nProduction scanner, strategy configuration, Git state, and paper-trade ledger are not intended targets." |
    Set-Content -Path $ReportPath -Encoding UTF8

$script:HadFailure = $false
function Log([string]$Message) {
    # Keep the report consistently UTF-8; Tee-Object can append UTF-16 data in Windows PowerShell 5.1.
    Add-Content -Path $ReportPath -Value $Message -Encoding UTF8
    Write-Host $Message
}
function Run-AllowedScript([string]$RelativePath) {
    $FullPath = Join-Path $Root $RelativePath
    Log ""
    Log ("=" * 72)
    Log "SCRIPT: $RelativePath"
    Log "START: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    if (-not (Test-Path $FullPath -PathType Leaf)) {
        Log "STATUS: SKIPPED — script not found."
        return
    }
    $Previous = Get-Location
    try {
        Set-Location $Root
        $Lines = & $Python $FullPath 2>&1
        $Code = $LASTEXITCODE
        foreach ($Line in $Lines) { Log ([string]$Line) }
        if ($Code -eq 0) { Log "STATUS: PASS (exit code 0)" }
        else { Log "STATUS: FAIL (exit code $Code)"; $script:HadFailure = $true }
    } catch {
        Log ("STATUS: FAIL — " + $_.Exception.Message)
        $script:HadFailure = $true
    } finally { Set-Location $Previous }
}

try {
    Log "`n========== PREFLIGHT =========="
    Log "Research output directory exists: $(Test-Path $ResearchOut)"
    $ObservationFile = Join-Path $ResearchOut "option_response_observations.csv"
    Log "Existing observation file exists: $(Test-Path $ObservationFile)"

    Log "`n========== INPUT DATE INVENTORY =========="
    foreach ($Spec in @(
        @{ Label = "OPTION-CHAIN"; Base = (Join-Path $Root "data\options_intelligence_upstox"); File = "option_chain_rows.csv.gz" },
        @{ Label = "OPTION-RETURNS"; Base = (Join-Path $Root "data\missed_opportunities"); File = "option_returns.json" }
    )) {
        $Dates = @()
        if (Test-Path $Spec.Base) {
            $Dates = @(Get-ChildItem $Spec.Base -Directory |
                Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' -and (Test-Path (Join-Path $_.FullName $Spec.File)) } |
                Sort-Object Name | ForEach-Object { $_.Name })
        }
        Log "$($Spec.Label) dates: $(if ($Dates.Count) { $Dates -join ', ' } else { 'none found' })"
    }

    Log "`n========== EXISTING OBSERVATION COVERAGE =========="
    if (Test-Path $ObservationFile) {
        $Code = @'
from pathlib import Path
import pandas as pd
p = Path(r"data\option_response_shadow_20261026\option_response_observations.csv")
df = pd.read_csv(p, low_memory=False)
print("Observation rows:", len(df))
print("Columns:", ", ".join(df.columns))
if "day" in df.columns:
    print("Rows by date:")
    print(df.groupby("day", dropna=False).size().to_string())
if "target_minutes" in df.columns:
    print("Rows by horizon:")
    print(df.groupby("target_minutes", dropna=False).size().to_string())
'@
        $Lines = $Code | & $Python - 2>&1
        $CheckCode = $LASTEXITCODE
        foreach ($Line in $Lines) { Log ([string]$Line) }
        if ($CheckCode -ne 0) { Log "STATUS: coverage check failed."; $script:HadFailure = $true }
    } else { Log "No observation file; skipping observation coverage check." }

    Log "`n========== ALLOWLISTED RESEARCH SCRIPTS =========="
    # These known research scripts may refresh their own research outputs.
    # No other scripts are executed.
    Run-AllowedScript "tools\research\audit_option_response_exit_quotes.py"
    Run-AllowedScript "tools\research\analyze_option_response_by_underlying_move.py"
    Run-AllowedScript "tools\research\analyze_entry_features_5m.py"

    Log "`n========== OUTPUT INVENTORY =========="
    foreach ($Dir in @($ResearchOut, $ReportDir)) {
        if (Test-Path $Dir) {
            Log "DIRECTORY: $Dir"
            Get-ChildItem $Dir -File | Sort-Object LastWriteTime -Descending |
                Select-Object -First 25 | ForEach-Object {
                    Log ("{0} | {1:N1} KB | {2}" -f $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss"), ($_.Length / 1KB), $_.Name)
                }
        }
    }

    Log "`n========== FINAL STATUS =========="
    if ($script:HadFailure) { Log "RESULT: COMPLETED WITH FAILURE(S); inspect this report." }
    else { Log "RESULT: COMPLETED; inspect script statuses and date coverage." }
    Log "REPORT: $ReportPath"
    Log "LIMITATION: This runner does not build missing observation dates or fabricate outcomes. Current date coverage depends on existing observations."
} finally {
}

Write-Host "`nShadow research run finished." -ForegroundColor Green
Write-Host "Report: $ReportPath" -ForegroundColor Cyan
if ($script:HadFailure) { Write-Host "Review failures in the report." -ForegroundColor Yellow }
