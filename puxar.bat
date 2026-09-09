@echo off
REM Só BUSCA o que está no GitHub. Não junta nada, não muda nenhum arquivo
REM seu — depois de rodar isto dá para olhar o que veio antes de decidir.
cd /d "C:\Users\marcu\Documents\saudi-football-monitor"
del /f .git\index.lock 2>nul
del /f .git\HEAD.lock 2>nul
git fetch origin
echo.
echo ===== O QUE ESTA NO GITHUB E NAO ESTA AQUI =====
git log --oneline HEAD..origin/main
echo.
echo ===== O QUE ESTA AQUI E NAO ESTA NO GITHUB =====
git log --oneline origin/main..HEAD
echo.
echo ===== FETCH FINISHED =====
pause
