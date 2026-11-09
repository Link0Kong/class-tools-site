@echo off
rem Dual-remote sync entry: GitHub (origin) + Gitee (gitee).
rem Usage: sync-repos.cmd "feat: summary of this change"
rem Real logic lives in sync_repos.py; this wrapper only cd's to the repo root and forwards args.
rem Keep this file ASCII-only: cmd.exe parses batch files with the OEM codepage, non-ASCII comments can break.
setlocal
chcp 65001 >nul 2>nul
cd /d "%~dp0"
set PYTHONUTF8=1
where python >nul 2>nul
if errorlevel 1 (
  echo [x] python not found in PATH. Install Python 3 and retry.
  exit /b 1
)
python "%~dp0sync_repos.py" %*
exit /b %ERRORLEVEL%
