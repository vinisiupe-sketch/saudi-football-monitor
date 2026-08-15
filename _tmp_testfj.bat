@echo off
set B=https://saudi-football-monitor-production.up.railway.app
set OUT=%~dp0_tmp_fj_result.txt
echo ===== EM ANDAMENTO 1602978 ===== > "%OUT%"
curl.exe -s -w "\nHTTP=%%{http_code}\n" --max-time 120 "%B%/api/numeros/fim-de-jogo?fixture=1602978" >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== HILAL 1602977 ===== >> "%OUT%"
curl.exe -s -w "\nHTTP=%%{http_code}\n" --max-time 120 "%B%/api/numeros/fim-de-jogo?fixture=1602977" >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== NEOM 1602975 ===== >> "%OUT%"
curl.exe -s -w "\nHTTP=%%{http_code}\n" --max-time 120 "%B%/api/numeros/fim-de-jogo?fixture=1602975" >> "%OUT%" 2>&1
echo. >> "%OUT%"
echo ===== FIXTURE INVALIDA ===== >> "%OUT%"
curl.exe -s -w "\nHTTP=%%{http_code}\n" --max-time 60 "%B%/api/numeros/fim-de-jogo?fixture=99999999" >> "%OUT%" 2>&1
