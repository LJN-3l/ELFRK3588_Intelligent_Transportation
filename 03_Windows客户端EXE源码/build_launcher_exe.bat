@echo off
setlocal
cd /d "%~dp0"

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
)

echo Building launcher executable...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --distpath "%~dp0" ^
  --name SmartTrafficAssistant ^
  launch_red_light_violation.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Launcher build finished:
echo %~dp0SmartTrafficAssistant.exe
pause
