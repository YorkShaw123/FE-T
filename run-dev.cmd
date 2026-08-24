@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Flora Editor] Missing .venv. Create it and install requirements.txt first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "server\app.py" %*
