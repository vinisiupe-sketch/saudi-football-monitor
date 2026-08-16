@echo off
cd /d "C:\Users\marcu\Documents\saudi-football-monitor"
del /f .git\index.lock 2>nul
del /f .git\HEAD.lock 2>nul
git checkout main
git reset --hard backup/pre-refactor-20260722
git push origin main --force
echo DONE
pause
