# Build standalone Windows distribution for LocalDictate using PyInstaller
$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython"
}

Write-Host "Ensuring PyInstaller is installed..." -ForegroundColor Cyan
& $venvPython -m pip install --quiet pyinstaller

Write-Host "Building LocalDictate (onedir, windowed)..." -ForegroundColor Cyan
& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "LocalDictate" `
    --paths "src" `
    --collect-data "faster_whisper" `
    --collect-all "ctranslate2" `
    --collect-all "onnxruntime" `
    "run.py"

Write-Host "Build completed: dist\LocalDictate\LocalDictate.exe" -ForegroundColor Green
