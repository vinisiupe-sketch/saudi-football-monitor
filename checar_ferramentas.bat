@echo off
chcp 65001 >nul
cd /d "%~dp0"
set OUT=ferramentas_status.txt

REM Escreve o resultado num arquivo em vez de so mostrar na tela, porque assim
REM eu consigo ler daqui. Nao instala nada, nao muda nada: so pergunta ao
REM Windows onde cada programa esta e qual a versao.

echo ===== CHECAGEM DE FERRAMENTAS =====> "%OUT%"
echo data: %DATE% %TIME%>> "%OUT%"
echo.>> "%OUT%"

echo -- onde estao -->> "%OUT%"
where yt-dlp  >> "%OUT%" 2>&1
where ffmpeg  >> "%OUT%" 2>&1
where ffprobe >> "%OUT%" 2>&1
where py      >> "%OUT%" 2>&1
where python  >> "%OUT%" 2>&1
where winget  >> "%OUT%" 2>&1
echo.>> "%OUT%"

echo -- versoes -->> "%OUT%"
echo [yt-dlp como programa]>> "%OUT%"
yt-dlp --version >> "%OUT%" 2>&1
echo [yt-dlp como modulo do python]>> "%OUT%"
REM Esta e a que importa. O Python 3.14 instala os programas dos pacotes num
REM diretorio fora do PATH, entao o pacote pode estar la e o comando "yt-dlp"
REM nao ser reconhecido. Chamar como modulo contorna isso.
py -3 -m yt_dlp --version >> "%OUT%" 2>&1
echo [ffmpeg]>> "%OUT%"
ffmpeg -version 2>&1 | findstr /B "ffmpeg version" >> "%OUT%"
echo [ffprobe]>> "%OUT%"
ffprobe -version 2>&1 | findstr /B "ffprobe version" >> "%OUT%"
echo [python]>> "%OUT%"
py -3 --version >> "%OUT%" 2>&1
echo.>> "%OUT%"

echo -- veredito -->> "%OUT%"
set FALTA=0
py -3 -m yt_dlp --version >nul 2>nul || (
  where yt-dlp >nul 2>nul || (echo FALTA yt-dlp ^(nem como programa nem como modulo^)>> "%OUT%" & set FALTA=1)
)
where ffmpeg  >nul 2>nul || (echo FALTA ffmpeg>> "%OUT%" & set FALTA=1)
where ffprobe >nul 2>nul || (echo FALTA ffprobe>> "%OUT%" & set FALTA=1)
if "%FALTA%"=="0" echo TUDO PRONTO>> "%OUT%"

type "%OUT%"
echo.
echo Resultado gravado em %OUT%
pause
