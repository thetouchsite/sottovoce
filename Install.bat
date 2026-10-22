@echo off
rem Creates .venv and installs everything, PyTorch first from the CUDA index.
rem Run it once. About 3.5 GB of downloads; the Whisper model (2.9 GB) comes
rem later, on the first transcription.
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Creating the virtual environment...
    %PY% -m venv .venv || goto :fail
)

echo.
echo   Installing PyTorch with CUDA...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cu130 || goto :fail

echo.
echo   Installing the rest...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail

if not exist "glossary.txt" copy /y "glossary.example.txt" "glossary.txt" >nul

echo.
".venv\Scripts\python.exe" -c "import torch; ok = torch.cuda.is_available(); print('  PyTorch', torch.__version__, '|', ('GPU: ' + torch.cuda.get_device_name(0)) if ok else 'NO GPU FOUND: it will run on the CPU, about ten times slower')"
echo.
echo   Done. Double-click Start.bat.
echo.
pause
exit /b 0

:fail
echo.
echo   Something went wrong above. See the README, section "Install".
echo.
pause
exit /b 1
