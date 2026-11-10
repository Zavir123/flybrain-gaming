@echo off
setlocal
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import pygame, numpy, scipy, pyarrow" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -m ensurepip --upgrade
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe main.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Launch failed. Install Python 3.11 or newer, then try again.
pause
exit /b 1
