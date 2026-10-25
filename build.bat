@echo off
rem Builds dist\GenshinScriptTranslator\GenshinScriptTranslator.exe
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2>nul || python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || goto :error
".venv\Scripts\python.exe" -m PyInstaller packaging\genshin-script-translator.spec --noconfirm || goto :error
echo.
echo Done: dist\GenshinScriptTranslator\GenshinScriptTranslator.exe
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1
