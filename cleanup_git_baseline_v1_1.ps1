param([string]$ProjectRoot=(Split-Path -Parent $MyInvocation.MyCommand.Path))
$ErrorActionPreference="Stop";Set-Location $ProjectRoot
$patterns=@(
"ChatGPT Installer.exe",
"Microsoft.Services.Store.winmd",
"type",
"*_before_*",
"*.backup_before_*",
"*.backup_*"
)
Add-Content .gitignore "`n# Local accidental/generated artifacts"
foreach($p in $patterns){Add-Content .gitignore $p}
foreach($p in $patterns){
  git ls-files -z -- $p | ForEach-Object {
    if($_){git rm --cached --ignore-unmatch -- $_}
  }
}
git add .gitignore validate_clean_session_runtime.py post_market_movement_forensic_v2_3.py run_post_market_movement_forensic_v2_3.bat
git diff --cached --quiet
if($LASTEXITCODE -ne 0){git commit -m "Clean baseline artifacts and correct validation/forensics tools"}
Write-Host "Git cleanup complete."
