$ErrorActionPreference = "Stop"
$env:QT_ENABLE_HIGHDPI_SCALING = "1"
Set-Location $PSScriptRoot

$projectPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (Test-Path -LiteralPath $projectPython) {
    $python = $projectPython
}
else {
    Write-Host "[ERROR] Project virtual environment was not found:" -ForegroundColor Red
    Write-Host "        $projectPython"
    Write-Host ""
    Write-Host "Create it from this folder with:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\python.exe -m pip install -r desktop_client\requirements.txt"
    Read-Host "Press Enter to close"
    exit 1
}

try {
    & $python .\main.py
    if ($LASTEXITCODE -ne 0) {
        throw "The client exited with code $LASTEXITCODE."
    }
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Review the error message above before closing this window."
    Read-Host "Press Enter to close"
    exit 1
}
