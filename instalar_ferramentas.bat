@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo  INSTALAR yt-dlp E ffmpeg
echo ==========================================================
echo.
echo  Os dois vem dos canais oficiais:
echo    yt-dlp  -^> PyPI, o repositorio oficial de pacotes Python
echo    ffmpeg  -^> winget, o gerenciador de pacotes da Microsoft
echo.
echo  Nada e baixado de fora desses dois lugares.
echo.
pause
echo.

REM ---------- 1. yt-dlp, via pip ----------
echo [1/2] yt-dlp
echo ----------------------------------------------------------
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (where python3 >nul 2>nul && set PY=python3)
if "%PY%"=="" (
  echo   Nao achei o Python nesta maquina.
  echo   Instale de https://www.python.org/downloads/
  echo   e MARQUE a caixa "Add python.exe to PATH" na primeira tela.
  goto ffmpeg
)
echo   usando: %PY%
%PY% -m pip install --upgrade yt-dlp
echo.

REM ---------- 2. ffmpeg, via winget ----------
:ffmpeg
echo [2/2] ffmpeg
echo ----------------------------------------------------------
where ffmpeg >nul 2>nul && (
  echo   ffmpeg ja esta instalado, pulando.
  goto verificar
)
where winget >nul 2>nul || (
  echo   Esta maquina nao tem o winget.
  echo   Baixe o ffmpeg de https://www.gyan.dev/ffmpeg/builds/
  echo   ^(pegue o "release essentials", descompacte, e adicione
  echo    a pasta bin ao PATH do Windows^)
  goto verificar
)
echo   instalando pelo winget...
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo.
  echo   O pacote "Gyan.FFmpeg" nao instalou.
  echo   Rode   winget search ffmpeg   num terminal para ver os
  echo   nomes disponiveis e instale o que aparecer.
)
echo.

REM ---------- 3. Conferir ----------
:verificar
echo ==========================================================
echo  CONFERINDO
echo ==========================================================
set FALTA=0
where yt-dlp  >nul 2>nul && (echo   yt-dlp   ok) || (echo   yt-dlp   NAO ENCONTRADO & set FALTA=1)
where ffmpeg  >nul 2>nul && (echo   ffmpeg   ok) || (echo   ffmpeg   NAO ENCONTRADO & set FALTA=1)
where ffprobe >nul 2>nul && (echo   ffprobe  ok) || (echo   ffprobe  NAO ENCONTRADO & set FALTA=1)
echo.
if "%FALTA%"=="1" (
  echo  ATENCAO: alguma ferramenta aparece como nao encontrada.
  echo.
  echo  Na maioria das vezes isso e so o PATH: o Windows so enxerga
  echo  o programa novo em janelas ABERTAS DEPOIS da instalacao.
  echo.
  echo  FECHE esta janela, abra o instalar_ferramentas.bat de novo,
  echo  e veja se agora aparecem as tres como ok. Se ainda faltar
  echo  alguma, ai e instalacao mesmo que nao deu certo.
) else (
  echo  Tudo pronto. Pode rodar o sondagem_live.bat.
)
echo.
pause
