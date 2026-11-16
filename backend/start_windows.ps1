$ErrorActionPreference = 'Stop'
$Backend = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Backend
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Run install_windows.ps1 first.' }
if (-not (Test-Path '.env')) { throw 'backend/.env is missing. Run install_windows.ps1 first.' }
$Worker = Start-Process -FilePath $Python -ArgumentList 'worker.py' -WorkingDirectory $Backend -PassThru -WindowStyle Minimized
Write-Host "RIS worker started (PID $($Worker.Id)). Press Ctrl+C to stop the API; stop the worker with Stop-Process -Id $($Worker.Id)."
try { & $Python -m uvicorn app:app --host 127.0.0.1 --port 8000 }
finally { if (-not $Worker.HasExited) { Stop-Process -Id $Worker.Id -Force -ErrorAction SilentlyContinue } }
