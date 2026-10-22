@echo off
rem Stops the server if its black window got lost or minimized.
rem The model lives inside that process: stopping it frees the VRAM too.
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 8200 -State Listen -ErrorAction SilentlyContinue; if($c){ Stop-Process -Id $c.OwningProcess -Force; Write-Host '  Sottovoce stopped.' } else { Write-Host '  It was not running.' }"
timeout /t 2 >nul
