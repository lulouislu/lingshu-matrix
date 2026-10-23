@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\macnet-lab.exe" (
  echo Run Python 3.11+ with scripts\install.py first.
  pause
  exit /b 1
)
".venv\Scripts\macnet-lab.exe" %*
