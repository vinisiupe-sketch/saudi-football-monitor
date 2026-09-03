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
rem
rem O "if exist ... goto" sozinho tem um buraco que custou caro: se o arquivo
rem existe mas esta ERRADO, reinstalar nao conserta nada — o instalador pula
rem a pergunta e a maquina segue sem conseguir falar com o app. Foi o que
rem aconteceu em 02/09/26: o arquivo tinha "ECHO esta ativado." dentro (bug
rem da versao anterior deste .bat, ver comentario mais abaixo), e rodar o
rem instalador de novo, e ate reiniciar o computador, nao mudava nada.
rem
rem Entao antes de confiar no arquivo, eu OLHO o que tem nele.
if not exist clipe_token.txt goto pede_senha
set "ATUAL="
set /p "ATUAL="<clipe_token.txt
echo(!ATUAL!| findstr /b /c:"ECHO " >nul
if not errorlevel 1 (
  echo    [!] A senha guardada aqui nao e uma senha: e sobra de um defeito
  echo        do instalador antigo. Vou apagar e pedir de novo.
  del /f clipe_token.txt
)
if exist clipe_token.txt goto tem_token

:pede_senha
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
rem COMO A SENHA E GRAVADA, e por que nao e do jeito obvio.
rem
rem A linha era esta:
rem     >clipe_token.txt echo^|set /p"=!TOKEN!"
rem
rem e ela GRAVAVA A COISA ERRADA. Numa linha com pipe, o redirecionamento
rem escrito na frente pertence ao PRIMEIRO comando — o echo — e nao ao
rem set /p, que e quem escreve a senha. Resultado: o arquivo ficava com a
rem mensagem que o echo sozinho imprime ("ECHO esta ativado.", 18 caracteres,
rem com acento) e a senha ia para a tela.
rem
rem Isso passou despercebido porque o arquivo EXISTIA e tinha texto dentro.
rem Na maquina de quem foi gravar, em 02/09/26, o efeito foi o gravador
rem passar horas sem conectar: o app recusava aquilo, e o acento ainda
rem derrubava a rota com 500 em vez de dizer "senha errada".
rem
rem O <nul manda o set /p ler de lugar nenhum (nao espera digitacao) e o
rem redirecionamento agora e do comando certo. Sem pipe, sem ambiguidade.
<nul set /p "=!TOKEN!" >clipe_token.txt

rem E CONFIRO o que ficou gravado. Escrever e torcer foi o que custou a noite.
set "GRAVADO="
set /p "GRAVADO="<clipe_token.txt
if "!GRAVADO!"=="!TOKEN!" (
  echo.
  echo    [ok] Senha guardada e CONFERIDA neste computador.
) else (
  echo.
  echo    [X] A senha nao foi gravada direito neste computador.
  echo        Ficou isto no arquivo:  !GRAVADO!
  echo        Abra o clipe_token.txt no Bloco de Notas, apague tudo, digite
  echo        a senha a mao e salve. Depois rode o gravador.bat.
  pause
)
:tem_token

if exist app_url.txt goto tem_url
<nul set /p "=https://saudi-football-monitor-production.up.railway.app" >app_url.txt
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
