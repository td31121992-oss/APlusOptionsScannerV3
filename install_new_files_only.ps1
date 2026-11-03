param(
  [string]$ProjectPath = "C:\Users\Aplus\Desktop\APlusOptionsScannerV3"
)
$ErrorActionPreference = "Stop"
$SourcePath = Split-Path -Parent $MyInvocation.MyCommand.Path
$Files = @("stock_option_response_shadow.py", "test_stock_option_response_shadow.py")
if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) {
  throw "Project folder not found: $ProjectPath"
}
foreach ($Name in $Files) {
  $Destination = Join-Path $ProjectPath $Name
  if (Test-Path -LiteralPath $Destination) {
    throw "Refusing to overwrite existing file: $Destination. Compare it manually first."
  }
}
foreach ($Name in $Files) {
  Copy-Item -LiteralPath (Join-Path $SourcePath $Name) -Destination (Join-Path $ProjectPath $Name)
}
Write-Host "Added new shadow module and tests. Existing project files were not changed." -ForegroundColor Green
Write-Host "Next run: python -m unittest -v test_stock_option_response_shadow.py"
