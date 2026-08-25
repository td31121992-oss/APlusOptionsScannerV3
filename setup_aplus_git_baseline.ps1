param([string]$ProjectRoot=(Split-Path -Parent $MyInvocation.MyCommand.Path))
$ErrorActionPreference="Stop"; Set-Location $ProjectRoot
function HasGit { try { git --version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false } }
Write-Host "APlus Git Baseline V1"
if(-not (HasGit)){
  $w=Get-Command winget -ErrorAction SilentlyContinue
  if(-not $w){Write-Host "FAIL: git and winget unavailable"; exit 2}
  winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
  $g="$env:ProgramFiles\Git\cmd"; if(Test-Path $g){$env:Path="$g;$env:Path"}
  if(-not (HasGit)){Write-Host "Git installed; reopen CMD and rerun."; exit 4}
}
@"
.env
.env.*
!.env.example
*.key
*.pem
__pycache__/
*.pyc
.venv/
venv/
logs/
data/
*.log
*.tmp
backup_before_*/
backup_*/
*.zip
.vscode/
.idea/
"@ | Set-Content .gitignore -Encoding UTF8
if(-not (Test-Path .git)){git init}
if(-not (git config user.name)){git config user.name "APlus Local Baseline"}
if(-not (git config user.email)){git config user.email "aplus-local@invalid.local"}
git add -A
git diff --cached --quiet
if($LASTEXITCODE -ne 0){git commit -m "APlus baseline after Breakout Confirmation and PAPER Circuit Breaker V1"}
$tag="aplus-paper-safety-baseline-2026-08-25"
if(-not (git tag --list $tag)){git tag -a $tag -m "APlus paper safety baseline"}
Write-Host "SUCCESS Git baseline"; git status --short
