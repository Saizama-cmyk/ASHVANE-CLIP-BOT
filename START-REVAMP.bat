@echo off
setlocal
cd /d "%~dp0"
if exist "artifacts\windows-revamp\Ashvane\Ashvane.exe" (
  start "" "artifacts\windows-revamp\Ashvane\Ashvane.exe"
  exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Ashvane needs its Windows build or the local Python environment.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m clipbot --window
