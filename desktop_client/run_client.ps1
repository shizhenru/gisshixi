$ErrorActionPreference = "Stop"
$env:QT_ENABLE_HIGHDPI_SCALING = "1"
Set-Location $PSScriptRoot
python .\main.py
