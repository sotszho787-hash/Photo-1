@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please double-click install_windows.bat first.
  pause
  exit /b 1
)
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m app.batch
) else (
  ".venv\Scripts\python.exe" -m app.batch --input "%~1"
)
set "MUJI_EXIT=%ERRORLEVEL%"
echo.
echo Photos and delivery ZIP: workspace\OUTPUT
echo Return code: %MUJI_EXIT% ^(2 means some photos failed; check report^)
pause
exit /b %MUJI_EXIT%
