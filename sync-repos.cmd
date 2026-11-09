@echo off
rem 双远端同步入口：GitHub(origin) + Gitee(gitee)。用法：sync-repos.cmd "feat: 说明"
rem 逻辑在 sync_repos.py；本文件只负责切到仓库根目录并转发参数。
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
