@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo [MUJI] Installing for one-click batch photo retouch...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 (
  echo Python 3.10+ required. Get it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed. Please check your network connection.
  pause
  exit /b 1
)
if not exist "workspace\INPUT" mkdir "workspace\INPUT"
if not exist "workspace\OUTPUT" mkdir "workspace\OUTPUT"
echo.
echo INSTALL COMPLETE. Put photos in workspace\INPUT, then double-click RUN_BATCH.bat.
pause
