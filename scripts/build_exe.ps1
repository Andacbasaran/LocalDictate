# Build standalone Windows distribution for LocalDictate by delegating to scripts/build_exe.py
$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython"
}

Write-Host "Ensuring PyInstaller is installed..." -ForegroundColor Cyan
& $venvPython -m pip install --quiet pyinstaller

$buildScript = Join-Path $PSScriptRoot "build_exe.py"
Write-Host "Running unified Windows builder: $buildScript" -ForegroundColor Cyan
& $venvPython $buildScript @args

Write-Host "Build completed: dist\LocalDictate\LocalDictate.exe" -ForegroundColor Green
