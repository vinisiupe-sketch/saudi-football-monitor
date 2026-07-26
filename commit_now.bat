@echo off
cd /d "C:\Users\marcu\Documents\saudi-football-monitor"
del /f .git\index.lock 2>nul
del /f .git\HEAD.lock 2>nul
git checkout main
git add main.py
git commit -m "refactor: guia Jogador com filtro unico consistente (clube+temporada+competicao via chips)"
git push origin main
echo DONE
pause
