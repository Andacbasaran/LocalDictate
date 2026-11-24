@echo off
chcp 65001 >nul
title LocalDictate v1.0.0 - Offline AI Voice Dictation Studio
cd /d "%~dp0.."

if exist "%~dp0..\dist\LocalDictate\LocalDictate.exe" (
    start "" "%~dp0..\dist\LocalDictate\LocalDictate.exe"
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creating Python virtual environment...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python 3.10+ not found on PATH.
        pause
        exit /b 1
    )
)

if not exist ".venv\.deps_installed" (
    echo [2/2] Installing LocalDictate dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
    type nul > ".venv\.deps_installed"
)

start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0
