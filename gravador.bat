@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Gravador de clipes - NAO FECHE durante o jogo
echo ===== GRAVADOR DE CLIPES =====
echo.
where py >nul 2>nul && (py -3 gravador.py & goto fim)
where python >nul 2>nul && (python gravador.py & goto fim)
where python3 >nul 2>nul && (python3 gravador.py & goto fim)
echo Nao achei o Python. Instale de https://www.python.org/downloads/
echo e marque "Add python.exe to PATH".
:fim
echo.
pause
