@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 需要 Python 3.8+：https://www.python.org/downloads/
  echo 装完再运行本文件。
  pause
  exit /b 1
)

python "%~dp0pcap.py" %*
set RC=%errorlevel%
if not "%RC%"=="0" (
  echo.
  echo [退出码 %RC%]
  pause
)
exit /b %RC%
