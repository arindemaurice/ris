@echo off
setlocal
cd /d "%~dp0"
if not exist .env py -3 setup.py
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
start "RIS Maintenance Worker" /D "%CD%" "%CD%\.venv\Scripts\python.exe" "%CD%\worker.py"
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
