$ErrorActionPreference = "Stop"
$env:QT_ENABLE_HIGHDPI_SCALING = "1"
Set-Location $PSScriptRoot
$python = $env:SPATIAL_VALIDATION_PYTHON
if (-not $python) {
    $python = "D:\Anaconda3_2024\Anaconda3_2024101\envs\gdal\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python).Source
}
$pythonHome = Split-Path $python -Parent
$env:PROJ_LIB = Join-Path $pythonHome "Library\share\proj"
$env:GDAL_DATA = Join-Path $pythonHome "Library\share\gdal"
& $python .\main.py
