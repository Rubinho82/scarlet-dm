@echo off
rem Abre o Scarlet DM sem janela de console.
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0main.py" %*
) else (
    start "" python "%~dp0main.py" %*
)
