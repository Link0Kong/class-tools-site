@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

where python >nul 2>nul
if errorlevel 1 (
  echo 需要 Python 3.8+：https://www.python.org/downloads/
  echo 安装时记得勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

python -c "import websocket" >nul 2>nul
if errorlevel 1 (
  echo 首次运行需要装一个依赖：
  python -m pip install websocket-client
)

echo.
echo 即将打开学校活动网页，请用「统一身份认证」登录（学号+密码）。
echo 登录成功后本窗口会自动继续，然后开始给工具站提供数据。
echo.
python agent.py login
if errorlevel 1 (
  echo 登录没完成。可以重新运行本文件，浏览器会保留登录状态。
  pause
  exit /b 1
)

python agent.py serve
pause
