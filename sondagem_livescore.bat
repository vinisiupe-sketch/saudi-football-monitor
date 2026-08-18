@echo off
setlocal
cd /d "%~dp0"
echo.
echo ===== LIVESCORE (leva ~3 minutos) =====
echo.
set PY=
py -3 --version >nul 2>&1
if not errorlevel 1 ( set PY=py -3& goto achou )
python --version >nul 2>&1
if not errorlevel 1 ( set PY=python& goto achou )
python3 --version >nul 2>&1
if not errorlevel 1 ( set PY=python3& goto achou )
echo NAO ACHEI O PYTHON.
pause
exit /b 1
:achou
%PY% sondagem_livescore.py
echo.
pause
