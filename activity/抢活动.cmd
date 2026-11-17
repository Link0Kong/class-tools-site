@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

where python >nul 2>nul
if errorlevel 1 (
  echo 需要 Python 3.8+：https://www.python.org/downloads/
  echo 安装时勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

python -c "import websocket" >nul 2>nul
if errorlevel 1 (
  echo 首次运行需要装一个依赖，正在安装…
  python -m pip install websocket-client
)

python grab.py
if errorlevel 1 pause
