@echo off
cd /d "C:\Users\marcu\Documents\saudi-football-monitor"
del /f .git\index.lock 2>nul
git add database.py janela_scraper.py
git commit -m "feat: order transfers by first_seen_at DESC (new entries first)"
git push
echo DONE
pause
