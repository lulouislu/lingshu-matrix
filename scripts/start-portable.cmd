@echo off
setlocal
cd /d "%~dp0"
"%~dp0MacNetLab.exe" %*
if errorlevel 1 (
  echo.
  echo MacNet Lab could not start. See the message above.
  pause
)
