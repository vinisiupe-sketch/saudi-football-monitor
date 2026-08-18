@echo off
setlocal
cd /d "%~dp0"
echo.
echo ===== SONDAGEM 2 SPORTMONKS =====
echo (a parte do livescore espera 70s de proposito)
echo.
set PY=
py -3 --version >nul 2>&1
if not errorlevel 1 ( set PY=py -3& goto achou )
python --version >nul 2>&1
if not errorlevel 1 ( set PY=python& goto achou )
python3 --version >nul 2>&1
if not errorlevel 1 ( set PY=python3& goto achou )
echo NAO ACHEI O PYTHON. Tentei: py -3 / python / python3
pause
exit /b 1
:achou
echo Usando: %PY%
%PY% sondagem2_sportmonks.py
echo.
echo ===== FIM =====
pause
