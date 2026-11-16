@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found. Run run_windows.bat once first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python worker.py
