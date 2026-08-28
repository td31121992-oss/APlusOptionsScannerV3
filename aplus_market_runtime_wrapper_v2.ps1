param([string]$ProjectRoot="C:\\Users\\Darpan.bobhate\\Desktop\\APlusOptionsScannerV3")
$ErrorActionPreference="Stop"
Set-Location $ProjectRoot
$watchdog=Join-Path $ProjectRoot "aplus_market_runtime_watchdog.ps1"
if(-not (Test-Path $watchdog)){throw "Missing watchdog: $watchdog"}
& $watchdog -ProjectRoot $ProjectRoot

function Count-PythonProcess([string]$pattern){
  $items=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '^python(.exe)?$' -and ([string]$_.CommandLine) -match $pattern
  })
  return [int]$items.Count
}

$scannerCount=Count-PythonProcess 'main\.py\s+--intraday-movement'
$safetyCount=Count-PythonProcess 'paper_safety_evidence_agent\.py'
$dashboardCount=Count-PythonProcess 'aplus_dashboard_v2\.py'
$campaignCount=Count-PythonProcess 'movement_campaign.*shadow|campaign.*shadow'

$now=Get-Date
$health=[ordered]@{
  as_of=$now.ToString("o")
  date=$now.ToString("yyyy-MM-dd")
  scanner_count=$scannerCount
  safety_agent_count=$safetyCount
  dashboard_v2_count=$dashboardCount
  campaign_shadow_count=$campaignCount
}
$health | ConvertTo-Json | Set-Content (Join-Path $ProjectRoot "data\aplus_automation_health.json") -Encoding UTF8
Write-Host ("HEALTH scanner={0} safety={1} dashboard={2} campaign={3}" -f $scannerCount,$safetyCount,$dashboardCount,$campaignCount)
