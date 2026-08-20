@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== SONDAGEM DA LIVE =====
echo.
where py >nul 2>nul && (py -3 sondagem_live.py & goto fim)
where python >nul 2>nul && (python sondagem_live.py & goto fim)
where python3 >nul 2>nul && (python3 sondagem_live.py & goto fim)
echo Nao achei o Python nesta maquina.
echo Instale de https://www.python.org/downloads/ e marque "Add to PATH".
:fim
echo.
pause
