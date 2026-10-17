@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Please run install_windows.bat first.
 pause
 exit /b 1
)
echo This OPTIONAL step copies the photo skill to %%USERPROFILE%%\.agents\skills\renovation-photo-retouch
 echo If an existing skill is present, it will be backed up first.
choice /M "Continue"
if errorlevel 2 exit /b 0
".venv\Scripts\python.exe" install_codex_skill.py
pause
