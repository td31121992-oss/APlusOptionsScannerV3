$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "APlusOptionsIntelligenceCollector"
$Health = Join-Path $ProjectRoot "data\options_intelligence\runtime_health.json"
$Log = Join-Path $ProjectRoot "data\logs\options_intelligence_runtime.log"

Write-Host "=== APlus Options Intelligence Runtime Verification ==="
Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Select-Object TaskName,State
Write-Host "--- Health evidence ---"
if (Test-Path $Health) { Get-Content $Health -Raw } else { Write-Host "Health file not present yet: $Health" }
Write-Host "--- Runtime log ---"
if (Test-Path $Log) { Get-Content $Log -Tail 40 } else { Write-Host "Runtime log not present yet: $Log" }
