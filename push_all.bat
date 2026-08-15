@echo off
cd /d "C:\Users\marcu\Documents\saudi-football-monitor"
del /f .git\index.lock 2>nul
del /f .git\HEAD.lock 2>nul
git push origin main
echo.
echo ===== PUSH FINISHED =====
pause
