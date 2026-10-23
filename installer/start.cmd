@echo off
rem Starts Sottovoce and opens the page once it answers. The installer's
rem launcher runs it; in a clone it works too, with .venv next to server.py.
rem Extra arguments go to server.py, e.g. --lan or --port 8300.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Not installed yet: see https://thetouchsite.github.io/sottovoce/getting-started/
    echo.
    pause
    exit /b 1
)

rem The port, if one was passed, for the page to open. SHIFT leaves %* whole.
set "PORT=8200"
:args
if "%~1"=="" goto started
if "%~1"=="--port" set "PORT=%~2"
shift
goto args
:started

title Sottovoce
echo.
echo   Sottovoce - starting. Closing this window stops it.
echo.
rem The page opens once the server answers, not before: the server takes a
rem few seconds to start, and a page opened too early shows an error.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "foreach ($n in 1..120) { try { Invoke-WebRequest 'http://127.0.0.1:%PORT%/health' -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process 'http://127.0.0.1:%PORT%'; break } catch { Start-Sleep 1 } }"
".venv\Scripts\python.exe" server.py %*
pause
