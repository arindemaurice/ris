$ErrorActionPreference = 'Stop'
$Backend = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Backend

$PythonCommand = $null
$PythonPrefix = @()
function Test-PythonVersion($Command, $Prefix) {
  $output = & $Command @Prefix --version 2>&1
  if ($LASTEXITCODE -ne 0) { return $false }
  if ($output -match 'Python\s+(\d+)\.(\d+)') {
    return ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11))
  }
  return $false
}
if (Get-Command py -ErrorAction SilentlyContinue) {
  foreach ($version in @('-3.13', '-3.12', '-3.11')) {
    if (Test-PythonVersion 'py' @($version)) { $PythonCommand = 'py'; $PythonPrefix = @($version); break }
  }
}
if (-not $PythonCommand -and (Get-Command python -ErrorAction SilentlyContinue)) {
  if (Test-PythonVersion 'python' @()) { $PythonCommand = 'python' }
}
if (-not $PythonCommand) {
  Write-Host 'Python 3.11+ was not found.' -ForegroundColor Yellow
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    $answer = Read-Host 'Install Python 3.12 using Windows Package Manager (winget)? [y/N]'
    if ($answer -match '^(y|yes)$') {
      winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
      Write-Host 'Close and reopen PowerShell, then run this installer again.' -ForegroundColor Yellow
      exit 0
    }
  }
  throw 'Install Python 3.11 or newer from https://www.python.org/downloads/windows/ and rerun this script.'
}

if (-not (Test-Path '.env')) { & $PythonCommand @PythonPrefix setup.py }
if (-not (Test-Path '.venv\Scripts\python.exe')) { & $PythonCommand @PythonPrefix -m venv .venv }
$VenvPython = Join-Path $Backend '.venv\Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Write-Host 'RIS dependencies installed. Start RIS with .\backend\start_windows.ps1 from the project root, or .\start_windows.ps1 from backend.' -ForegroundColor Green
