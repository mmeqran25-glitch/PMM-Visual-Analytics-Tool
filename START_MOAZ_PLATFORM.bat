@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_moaz_platform.ps1"
if errorlevel 1 (
  echo.
  echo The platform launcher reported an error.
  pause
)
