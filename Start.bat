@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Not installed yet: double-click Install.bat first.
    echo.
    pause
    exit /b 1
)
echo.
echo   Sottovoce - starting...
echo.
start "" http://127.0.0.1:8200
".venv\Scripts\python.exe" server.py
pause
