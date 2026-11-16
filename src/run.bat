@echo off
rem =====================================================================
rem  Perfect Campus Power Monitor - Windows launcher (ASCII only)
rem  Docs: README_zh.md
rem
rem  Usage:
rem    run.bat                         show ledger status (same as "status")
rem    run.bat doctor                  dependency / config / network checks
rem    run.bat projects                list payment projects -> fill payproid
rem    run.bat rooms --building 11 --room 616
rem                                    find roomverify
rem    run.bat now                     read remaining kWh once (alias: state)
rem    run.bat test                    read once + push a test message
rem    run.bat sample                  one sample into SQLite ledger + low alert
rem    run.bat report --dry            print last week report, do not push
rem    run.bat secure                  tighten permissions of local files
rem    run.bat install                 print schtasks commands
rem
rem  wanxiao fallback (only if backend=wanxiao; needs phone/password):
rem    run.bat login                   password login (no SMS)
rem    run.bat sms-send                send one SMS code
rem    run.bat sms-code 123456         submit the SMS code (binds deviceId)
rem    run.bat sms                     send SMS + type code interactively
rem    run.bat wx-status               show login state (masked)
rem
rem  Tips:
rem    * Any monitor command accepts  --log logs\monitor.log
rem    * Windows console is switched to UTF-8 below.
rem =====================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONLEGACYWINDOWSSTDIO=0"
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python.exe not found in PATH.
    echo         Install Python 3.8+ and enable "Add python.exe to PATH".
    exit /b 1
)

if "%~1"=="" goto :monitor_status

set "CMD=%~1"
if /i "%CMD%"=="login"     goto :wanxiao
if /i "%CMD%"=="sms"       goto :wanxiao
if /i "%CMD%"=="sms-send"  goto :wanxiao
if /i "%CMD%"=="sms-code"  goto :wanxiao
if /i "%CMD%"=="token"     goto :wanxiao
if /i "%CMD%"=="wx-status" goto :wanxiao

:monitor
"%PY%" "%~dp0electricity_monitor.py" %*
exit /b %errorlevel%

:monitor_status
"%PY%" "%~dp0electricity_monitor.py" status
exit /b %errorlevel%

:wanxiao
set "SUB=%~1"
if /i "%SUB%"=="wx-status" set "SUB=status"
shift
"%PY%" "%~dp0wanxiao_login.py" "%SUB%" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%
