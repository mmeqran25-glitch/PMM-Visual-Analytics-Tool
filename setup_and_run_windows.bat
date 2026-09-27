@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo PMM Visual Analytics ^& Presentation Tool v0.7.0
echo Excel MASTER remains the source of truth.
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating local Python environment...
  py -m venv .venv
  if errorlevel 1 goto :error
) else (
  echo [1/3] Local Python environment already exists.
)

echo [2/3] Installing/updating required packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] Starting PMM visual tool...
".venv\Scripts\python.exe" -m streamlit run app.py
goto :eof

:error
echo.
echo Setup or startup failed. Keep this window open and send a screenshot of the error.
pause
