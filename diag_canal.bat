@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Diagnostico do canal
where py >nul 2>nul && (py -3 diag_canal.py & goto fim)
where python >nul 2>nul && (python diag_canal.py & goto fim)
where python3 >nul 2>nul && (python3 diag_canal.py & goto fim)
echo Nao achei o Python.
:fim
