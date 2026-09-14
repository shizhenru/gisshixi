@echo off
set QT_ENABLE_HIGHDPI_SCALING=1
cd /d "%~dp0"
if defined SPATIAL_VALIDATION_PYTHON (
  set "PYTHON_EXE=%SPATIAL_VALIDATION_PYTHON%"
) else (
  set "PYTHON_EXE=D:\Anaconda3_2024\Anaconda3_2024101\envs\gdal\python.exe"
)
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
for %%I in ("%PYTHON_EXE%") do set "PYTHON_HOME=%%~dpI"
set "PROJ_LIB=%PYTHON_HOME%\Library\share\proj"
set "GDAL_DATA=%PYTHON_HOME%\Library\share\gdal"
"%PYTHON_EXE%" main.py
