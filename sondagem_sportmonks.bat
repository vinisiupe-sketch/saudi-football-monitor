@echo off
setlocal
cd /d "%~dp0"
echo.
echo ===== SONDAGEM SPORTMONKS =====
echo.

REM O Windows tem varios jeitos de chamar o Python e nem sempre "python"
REM esta no PATH. Tento os tres em ordem e digo qual funcionou, em vez de
REM fechar a janela em silencio como aconteceu da primeira vez.
set PY=

py -3 --version >nul 2>&1
if not errorlevel 1 (
  set PY=py -3
  goto achou
)

python --version >nul 2>&1
if not errorlevel 1 (
  set PY=python
  goto achou
)

python3 --version >nul 2>&1
if not errorlevel 1 (
  set PY=python3
  goto achou
)

echo NAO ACHEI O PYTHON nesta maquina.
echo.
echo Tentei: py -3   /   python   /   python3
echo.
echo Voce tem o Python 3.14 instalado, entao provavelmente e so
echo o PATH. Instale de novo marcando "Add Python to PATH", ou
echo me avise que a gente resolve de outro jeito.
echo.
pause
exit /b 1

:achou
echo Usando: %PY%
%PY% --version
echo.
%PY% sondagem_sportmonks.py

echo.
echo ===== FIM =====
echo Se apareceu erro acima, me mande o print.
echo.
pause
