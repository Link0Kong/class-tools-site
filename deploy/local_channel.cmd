@echo off
rem =====================================================================
rem  班级工具站 · 本地临时通道（域名暂停期间在本机使用网站）
rem  双击本文件：启动本地通道并自动打开浏览器；关闭黑色窗口即停止。
rem  原理：把页面里的 CloudBase 基址改成同源 /__cb/，由本脚本在服务端
rem        带上 Origin=https://tool.furina.fun 转发到 CloudBase（绕开
rem        DNS 暂停 + 网关 CORS 白名单），只监听 127.0.0.1，仅本机可用。
rem =====================================================================
setlocal
chcp 65001 >nul 2>nul
cd /d "%~dp0.."
set PYTHONUTF8=1
where python >nul 2>nul
if errorlevel 1 (
  echo [x] 没有找到 python，请确认 Python 3 已加入 PATH。
  pause
  exit /b 1
)
echo 正在启动本地临时通道... 浏览器会自动打开 http://127.0.0.1:8787/
echo 使用完毕后：在本窗口按 Ctrl+C 或直接关闭窗口即可停止。
rem 支持传参（如 --port 8899）；不传参时默认 --open
if "%~1"=="" (
  python "%~dp0local_channel.py" --open
) else (
  python "%~dp0local_channel.py" %*
)
if errorlevel 1 pause
exit /b %ERRORLEVEL%
