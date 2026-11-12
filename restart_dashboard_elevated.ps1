# Restart the live P&L dashboard (port 8765). Run from an ELEVATED PowerShell: the dashboard runs elevated, so a normal session cannot stop it.
#   powershell -ExecutionPolicy Bypass -File .\restart_dashboard_elevated.ps1
# Stops whatever listens on 8765 (and its python launcher parent), then starts run_live_pnl_dashboard.bat. Paper trades live in the journal file and are not touched.
param([string]$ProjectRoot = "C:\Users\Aplus\Desktop\APlusOptionsScannerV3", [int]$Port = 8765)
$ErrorActionPreference = "Stop"
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run this from an elevated (Administrator) PowerShell." }

$owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($o in $owners) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$o"
    $parent = if ($proc) { Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" } else { $null }
    Write-Host "stopping $o ($($proc.CommandLine))"
    Stop-Process -Id $o -Force
    if ($parent -and $parent.Name -match "^python" -and $parent.CommandLine -match "aplus_live_pnl_dashboard") { Write-Host "stopping launcher $($parent.ProcessId)"; Stop-Process -Id $parent.ProcessId -Force }
}
for ($i = 0; $i -lt 20; $i++) { if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Milliseconds 500 }
Start-Process cmd -ArgumentList "/c", "`"$ProjectRoot\run_live_pnl_dashboard.bat`"" -WindowStyle Hidden
for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { Write-Host "dashboard is listening on $Port"; exit 0 } }
Write-Host "dashboard did not come back on $Port within 20 s - check data\logs\aplus_live_pnl_dashboard.log"; exit 1
