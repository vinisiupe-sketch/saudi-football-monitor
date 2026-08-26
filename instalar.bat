@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Instalar o Gravador de Clipes

echo.
echo  ============================================================
echo    GRAVADOR DE CLIPES
echo  ============================================================
echo.
echo    Isto roda UMA VEZ. Depois o programa sobe sozinho com o
echo    Windows e fica no icone ao lado do relogio.
echo.

rem ================================================================ Python
set PY=
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo    [X] Nao achei o Python neste computador.
  echo.
  echo        1. Abra  https://www.python.org/downloads/
  echo        2. Baixe e abra o instalador
  echo        3. MARQUE a caixinha "Add python.exe to PATH" na PRIMEIRA tela
  echo        4. Termine e rode este arquivo de novo
  echo.
  pause
  exit /b 1
)
echo    [ok] Python encontrado.

rem ============================================== bibliotecas do programa
echo    [..] Instalando o que o programa precisa. Pode levar um minuto.
%PY% -m pip install --quiet --upgrade yt-dlp pystray pillow
if errorlevel 1 (
  echo    [X] Falhou. Confira se a internet esta funcionando e tente de novo.
  pause
  exit /b 1
)
echo    [ok] Pronto.

rem ================================================================ ffmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo    [..] Instalando o ffmpeg. Aceite se aparecer alguma pergunta.
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  echo.
  echo    ============================================================
  echo     IMPORTANTE: feche esta janela e rode o instalar.bat de novo.
  echo     O Windows so enxerga o ffmpeg depois que a janela reabre.
  echo    ============================================================
  echo.
  pause
  exit /b 0
)
echo    [ok] ffmpeg encontrado.

rem ================================================================= senha
if exist clipe_token.txt goto tem_token
echo.
echo    Cole abaixo a senha que o Vini te mandou e aperte Enter.
echo    (ela nao publica nada; so deixa este computador entregar os videos)
echo.
set "TOKEN="
set /p "TOKEN=   senha: "
if not defined TOKEN (
  echo    [X] Sem a senha eu nao consigo falar com o aplicativo.
  pause
  exit /b 1
)
>clipe_token.txt echo|set /p"=!TOKEN!"
echo.
echo    [ok] Senha guardada neste computador.
:tem_token

if exist app_url.txt goto tem_url
>app_url.txt echo|set /p"=https://saudi-football-monitor-production.up.railway.app"
:tem_url

rem ==================================================== iniciar com Windows
rem O pythonw roda SEM a janela preta. E a janela preta nao e frescura: o
rem console do Windows PAUSA o programa quando alguem clica dentro dele para
rem selecionar texto, e a gravacao morre sem erro nenhum, sem aviso nenhum.
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYW set "PYW=%%~dpipythonw.exe"
)
if not defined PYW (
  echo    [!] Nao achei o pythonw. Vou usar o python normal, e vai aparecer
  echo        uma janela preta. NAO CLIQUE DENTRO DELA - clicar pausa o
  echo        programa. Pode minimizar a vontade.
  set "PYW=python"
)

rem Atalho na pasta de inicializacao. Escolhi isto no lugar do agendador de
rem tarefas porque o agendador exige aspas dentro de aspas na linha de
rem comando, e essa e uma das coisas que mais quebram em .bat sem ninguem
rem entender por que.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a=[Environment]::GetFolderPath('Startup')+'\Gravador de Clipes.lnk';" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($a);" ^
  "$s.TargetPath='%PYW%';" ^
  "$s.Arguments='\"%~dp0gravador.py\"';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.Description='Gravador de clipes';" ^
  "$s.Save()" >nul 2>nul
if errorlevel 1 (
  echo    [!] Nao consegui deixar automatico. Voce vai precisar dar dois
  echo        cliques em gravador.bat antes dos jogos.
) else (
  echo    [ok] Vai iniciar junto com o Windows.
)

rem ============================================================= comecar ja
echo    [..] Ligando.
start "" "%PYW%" "%~dp0gravador.py"

echo.
echo  ============================================================
echo    PRONTO. Procure o icone ao lado do relogio:
echo.
echo      cinza     ligado, nenhum jogo gravando
echo      verde     gravando
echo      vermelho  deu problema (clique com o botao direito para ver)
echo.
echo    Nao precisa abrir nada antes dos jogos.
echo    So deixe o computador ligado e sem dormir.
echo  ============================================================
echo.
pause
