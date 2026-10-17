@echo off
rem Cria atalhos do Scarlet DM na Área de Trabalho e no Menu Iniciar (com o ícone vermelho).
cd /d "%~dp0"
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
    echo pythonw.exe nao encontrado no PATH.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))) {" ^
  "  $l = $s.CreateShortcut((Join-Path $dir 'Scarlet DM.lnk'));" ^
  "  $l.TargetPath = '%PYW%';" ^
  "  $l.Arguments = '\"%~dp0main.py\"';" ^
  "  $l.WorkingDirectory = '%~dp0';" ^
  "  $l.IconLocation = '%~dp0assets\app.ico';" ^
  "  $l.Description = 'Scarlet DM - gerenciador de downloads';" ^
  "  $l.Save() }"
echo Atalhos criados na Area de Trabalho e no Menu Iniciar.
pause
