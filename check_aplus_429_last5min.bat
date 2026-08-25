@echo off
setlocal
cd /d "C:\Users\Darpan.bobhate\Desktop\APlusOptionsScannerV3"
title APlus 429 Diagnostic Check

echo ============================================================
echo APlus 429 Diagnostic Check - Last 5 Minutes Approx.
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$cut=(Get-Date).AddMinutes(-5);" ^
  "$lines=Get-Content 'logs\scanner.log';" ^
  "$recent=$lines | Where-Object { if($_ -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'){ try{([datetime]::ParseExact($matches[1],'yyyy-MM-dd HH:mm:ss',$null)) -ge $cut}catch{$false} } else {$false} };" ^
  "$err=@($recent | Where-Object { $_ -match '429 Client Error' });" ^
  "$cycles=@($recent | Where-Object { $_ -match 'Intraday movement cycle' });" ^
  "Write-Host ('429 COUNT (recent): '+$err.Count);" ^
  "Write-Host ('SCANNER CYCLES (recent): '+$cycles.Count);" ^
  "Write-Host '';" ^
  "$err | Select-Object -Last 20;" ^
  "Write-Host '';" ^
  "$cycles | Select-Object -Last 10"

echo.
pause
endlocal
