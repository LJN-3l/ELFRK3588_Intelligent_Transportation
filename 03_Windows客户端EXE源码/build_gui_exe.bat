@echo off
setlocal
cd /d "%~dp0"

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
)

echo Building executable...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name SmartTrafficAssistant ^
  --collect-all ultralytics ^
  red_light_violation_gui.py

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build finished:
echo %~dp0dist\SmartTrafficAssistant\SmartTrafficAssistant.exe
pause
