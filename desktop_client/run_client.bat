@echo off
setlocal
set "QT_ENABLE_HIGHDPI_SCALING=1"
cd /d "%~dp0"

if exist "%~dp0..\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
) else (
  echo [ERROR] Project virtual environment was not found:
  echo         %~dp0..\.venv\Scripts\python.exe
  echo.
  echo Create it from this folder with:
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r desktop_client\requirements.txt
  echo.
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python executable was not found:
  echo         %PYTHON_EXE%
  echo.
  pause
  exit /b 1
)

"%PYTHON_EXE%" main.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] The client exited with code %APP_EXIT_CODE%.
  echo Review the error message above before closing this window.
  echo.
  pause
)
exit /b %APP_EXIT_CODE%
