@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $s=$ws.CreateShortcut((Join-Path $desktop 'Moaz PMM Research Platform.lnk')); $s.TargetPath=(Join-Path '%~dp0' 'START_MOAZ_PLATFORM.bat'); $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,220'; $s.Save()"
if errorlevel 1 (
  echo Could not create the desktop shortcut.
  pause
  exit /b 1
)
echo Desktop shortcut created: Moaz PMM Research Platform
pause
