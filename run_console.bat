@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\installed.ok" (
    echo Run run.bat first to install the dependencies.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py %*
pause
