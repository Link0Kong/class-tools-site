@echo off
setlocal
cd /d "%~dp0"
set MSG=%~1
if "%MSG%"=="" set MSG=chore: sync
echo [1/4] staging...
git add -A || goto :fail
echo [2/4] committing...
git commit -m "%MSG%"
if errorlevel 1 echo (nothing to commit or commit failed - continuing)
echo [3/4] pushing GitHub...
git push origin master || goto :fail
echo [4/4] pushing Gitee...
git push gitee master || goto :fail
echo.
echo DONE. Both remotes updated.
git log --oneline -1
exit /b 0
:fail
echo.
echo FAILED at previous step. Nothing else was pushed.
exit /b 1