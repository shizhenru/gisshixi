@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating project virtual environment...
  python -m venv .venv
  if errorlevel 1 (echo Failed to create .venv.& pause& exit /b 1)
)
echo Installing or updating desktop client dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency installation failed.& pause& exit /b 1)
echo Setup complete. You can now double-click run_client.bat.
pause
