$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "..\aplus_master_self_healing_supervisor.ps1"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    throw "Supervisor parser errors: $($parseErrors -join '; ')"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-ScannerHealthState"
}, $true)
if (-not $functionAst) {
    throw "Get-ScannerHealthState function was not found"
}
Invoke-Expression $functionAst.Extent.Text

$cases = @(
    @{ Count = 1; Fresh = $true;  Market = $true;  Visibility = "VISIBLE";      Health = "HEALTHY" },
    @{ Count = 0; Fresh = $true;  Market = $true;  Visibility = "UNKNOWN";      Health = "UNKNOWN_VISIBILITY" },
    @{ Count = 0; Fresh = $false; Market = $true;  Visibility = "NOT_DETECTED"; Health = "FAILED_DURING_MARKET" },
    @{ Count = 0; Fresh = $false; Market = $false; Visibility = "NOT_DETECTED"; Health = "STOPPED_MARKET_CLOSED" },
    @{ Count = 1; Fresh = $false; Market = $true;  Visibility = "VISIBLE";      Health = "STALE_REPORT_DURING_MARKET" },
    @{ Count = 2; Fresh = $true;  Market = $true;  Visibility = "VISIBLE";      Health = "DUPLICATE_INSTANCES" }
)

foreach ($case in $cases) {
    $actual = Get-ScannerHealthState -ScannerCount $case.Count -ReportFresh $case.Fresh -Market $case.Market
    if ($actual.ProcessVisibility -ne $case.Visibility -or $actual.Health -ne $case.Health) {
        throw "Unexpected state for count=$($case.Count), fresh=$($case.Fresh), market=$($case.Market): $($actual | ConvertTo-Json -Compress)"
    }
}

Write-Output "PASS: $($cases.Count) scanner health classification cases"
