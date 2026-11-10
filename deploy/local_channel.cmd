@echo off
rem ASCII-only launcher (cmd.exe parses batch files in OEM codepage; keep this file ASCII + CRLF).
setlocal
cd /d "%~dp0.."
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "C:\Windows\py.exe" set "PY=C:\Windows\py.exe"
if not defined PY set "PY=python"
echo ============================================================
echo  Class Tools - Local Channel (temporary, this PC only)
echo  Browser will open http://127.0.0.1:8787/
echo  Close this window to stop the channel.
echo ============================================================
if "%~1"=="" (
  "%PY%" "%~dp0local_channel.py" --open
) else (
  "%PY%" "%~dp0local_channel.py" %*
)
if errorlevel 1 pause
exit /b %ERRORLEVEL%
