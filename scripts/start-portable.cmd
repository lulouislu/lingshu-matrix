@echo off
setlocal
cd /d "%~dp0"
"%~dp0LingShuMatrix.exe" %*
if errorlevel 1 (
  echo.
  echo LingShu Matrix could not start. See the message above.
  pause
)
