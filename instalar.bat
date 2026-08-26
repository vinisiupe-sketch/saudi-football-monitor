@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar o Gravador de Clipes
color 0F

echo.
echo  ===========================================================
echo   GRAVADOR DE CLIPES - instalacao
echo  ===========================================================
echo.
echo   Isto roda uma vez so. Depois o programa sobe sozinho com o
echo   Windows e fica no icone ao lado do relogio.
echo.

rem ---------------------------------------------------------------- Python
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo   [X] Nao achei o Python nesta maquina.
  echo.
  echo       Baixe em  https://www.python.org/downloads/
  echo       e MARQUE a caixinha "Add python.exe to PATH" na primeira tela.
  echo       Depois rode este instalador de novo.
  echo.
  pause
  exit /b 1
)
echo   [ok] Python encontrado.

rem ------------------------------------------------------- yt-dlp e amigos
echo   [..] Instalando yt-dlp e o icone da bandeja. Pode demorar um minuto.
%PY% -m pip install --quiet --upgrade yt-dlp pystray pillow
if errorlevel 1 (
  echo   [X] A instalacao das bibliotecas falhou. Confira a internet.
  pause
  exit /b 1
)
echo   [ok] Bibliotecas instaladas.

rem ---------------------------------------------------------------- ffmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo   [..] Instalando o ffmpeg pelo winget.
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  echo.
  echo   [!] Se o ffmpeg acabou de ser instalado, FECHE esta janela e rode
  echo       o instalador de novo - o Windows so enxerga o programa novo
  echo       depois que a janela reabre.
  echo.
  pause
  exit /b 0
)
echo   [ok] ffmpeg encontrado.

rem ----------------------------------------------------------------- token
if exist clipe_token.txt goto tem_token
echo.
echo   Cole a senha que o Vini te passou e aperte Enter.
echo   (ela nao publica nada; so deixa esta maquina entregar os clipes)
echo.
set /p TOKEN=  senha:
if "%TOKEN%"=="" (
  echo   [X] Sem a senha eu nao consigo falar com o app.
  pause
  exit /b 1
)
> clipe_token.txt echo|set /p="%TOKEN%"
echo   [ok] Senha guardada.
:tem_token

if exist app_url.txt goto tem_url
> app_url.txt echo|set /p="https://saudi-football-monitor-production.up.railway.app"
:tem_url

rem -------------------------------------------------- iniciar com o Windows
rem O pythonw roda sem janela preta. E a janela preta nao e detalhe: o console
rem do Windows PAUSA o programa quando alguem clica dentro dele, e a gravacao
rem morre sem aviso nenhum.
set PYW=%LOCALAPPDATA%\Programs\Python\Launcher\pyw.exe
if not exist "%PYW%" set PYW=pythonw

schtasks /create /tn "Gravador de Clipes" /tr "\"%PYW%\" \"%~dp0gravador.py\"" ^
  /sc onlogon /rl limited /f >nul 2>nul
if errorlevel 1 (
  echo   [!] Nao consegui agendar o inicio automatico. Vou deixar um atalho
  echo       na pasta de inicializacao, que faz a mesma coisa.
  powershell -NoProfile -Command ^
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Gravador de Clipes.lnk'); $s.TargetPath='%PYW%'; $s.Arguments='\"%~dp0gravador.py\"'; $s.WorkingDirectory='%~dp0'; $s.Save()" >nul 2>nul
) else (
  echo   [ok] Vai iniciar junto com o Windows.
)

rem ------------------------------------------------------------- comecar ja
echo   [..] Ligando o gravador.
start "" "%PYW%" "%~dp0gravador.py"

echo.
echo  ===========================================================
echo   Pronto. Procure o icone ao lado do relogio:
echo.
echo     cinza    - ligado, sem jogo gravando
echo     verde    - gravando
echo     vermelho - deu algum problema (clique para ver)
echo.
echo   Nao precisa abrir nada antes dos jogos. Ele ja fica de pe.
echo  ===========================================================
echo.
pause
