@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

where python >nul 2>nul
if errorlevel 1 (
  echo 需要 Python 3.8+：https://www.python.org/downloads/
  pause
  exit /b 1
)

python agent.py serve
pause
