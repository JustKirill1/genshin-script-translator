@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\installed.ok" (
    echo First start: creating the environment and installing dependencies, this takes a couple of minutes...
    if not exist ".venv\Scripts\python.exe" (
        py -3 -m venv .venv 2>nul || python -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" (
        echo Python 3.10+ was not found. Install it from python.org and run this file again.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (
        echo Could not install the dependencies.
        pause
        exit /b 1
    )
    echo ok> ".venv\installed.ok"
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
