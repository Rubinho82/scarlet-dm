@echo off
rem Gera o Scarlet DM pronto para distribuir (nao precisa de Python instalado para rodar o resultado).
rem   build_exe.bat           pasta portatil dist\ScarletDM\ScarletDM.exe
rem   build_exe.bat release   + release\: instalador (Setup.exe), portatil .zip, codigo-fonte .zip,
rem                           extensoes do navegador (.zip) e SHA256SUMS.txt
rem Variaveis opcionais (ex.: para gerar em outro disco quando o C: esta cheio):
rem   SDM_DIST    pasta do app gerado (padrao: dist)
rem   SDM_BUILD   arquivos temporarios do build (padrao: build)
rem   SDM_RELEASE pasta dos pacotes para publicar (padrao: release)
setlocal
cd /d "%~dp0"
if not defined SDM_DIST set "SDM_DIST=dist"
if not defined SDM_BUILD set "SDM_BUILD=build"
if not defined SDM_RELEASE set "SDM_RELEASE=release"
rem caminhos absolutos (o PyInstaller interpreta caminhos relativos a partir da pasta do .spec)
for %%I in ("%SDM_DIST%") do set "SDM_DIST=%%~fI"
for %%I in ("%SDM_BUILD%") do set "SDM_BUILD=%%~fI"
for %%I in ("%SDM_RELEASE%") do set "SDM_RELEASE=%%~fI"
rem cache do PyInstaller junto dos temporarios (nao enche o disco C: quando o build e em outro disco)
if not defined PYINSTALLER_CONFIG_DIR set "PYINSTALLER_CONFIG_DIR=%SDM_BUILD%\pyi-cache"

rem Python com as dependencias: SDM_PY (ex.: um venv com PyInstaller de bootloader compilado localmente,
rem que reduz alarme falso de antivirus), senao o 3.10 via "py", senao o python do PATH.
set "PY=python"
py -3.10 -c "import sys" >nul 2>nul && set "PY=py -3.10"
if defined SDM_PY set "PY=%SDM_PY%"
echo Usando: %PY%
%PY% --version || goto :fail

rem So chama o pip se faltar algo (evita mexer num ambiente que ja funciona).
%PY% -c "import PySide6, requests, cryptography, PyInstaller" >nul 2>nul || (
  %PY% -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || goto :fail
)
%PY% -c "import libtorrent" >nul 2>nul || echo AVISO: libtorrent ausente - o .exe vai sair sem suporte a torrent/magnet.

rem Nao apaga a pasta de um Scarlet que esta aberto (quebraria o programa em uso).
%PY% -c "import os,sys;sys.path.insert(0,'.');from scarlet.install import running_instances as r;sys.exit(1 if r(os.path.abspath(r'%SDM_DIST%\ScarletDM')) else 0)" || (
  echo O Scarlet DM de %SDM_DIST%\ScarletDM esta aberto. Feche-o ^(icone perto do relogio - Sair^) ou use outra pasta:
  echo   set SDM_DIST=build\dist
  goto :fail
)
if exist "%SDM_DIST%\ScarletDM" rmdir /s /q "%SDM_DIST%\ScarletDM"
if not exist build mkdir build
%PY% tools\build_installer.py --version-file build\version-app.txt || goto :fail

%PY% -m PyInstaller --noconfirm --clean ^
  --distpath "%SDM_DIST%" --workpath "%SDM_BUILD%\pyi" ^
  --onedir --windowed ^
  --name ScarletDM ^
  --icon "%CD%\assets\app.ico" ^
  --version-file build\version-app.txt ^
  --add-data "%CD%\assets;assets" ^
  --add-data "%CD%\scarlet\locales;scarlet\locales" ^
  --hidden-import PySide6.QtSvg ^
  --hidden-import PySide6.QtNetwork ^
  --hidden-import PySide6.QtMultimedia ^
  --hidden-import PySide6.QtMultimediaWidgets ^
  --hidden-import cryptography.hazmat.primitives.ciphers ^
  --collect-binaries libtorrent ^
  --hidden-import libtorrent ^
  --exclude-module tkinter ^
  --exclude-module numpy ^
  --exclude-module matplotlib ^
  --exclude-module PIL ^
  --exclude-module pandas ^
  --exclude-module IPython ^
  --exclude-module Crypto ^
  --exclude-module Cryptodome ^
  main.py || goto :fail

rem Tira partes do Qt que o app nao usa (~45 MB a menos).
%PY% tools\trim_dist.py "%SDM_DIST%\ScarletDM" || goto :fail

rem Extensao do navegador ao lado do .exe (Preferencias > Navegador aponta para elas): Chromium e Firefox.
%PY% tools\package_extension.py "%SDM_BUILD%\extensions" || goto :fail
xcopy /e /i /q /y extension "%SDM_DIST%\ScarletDM\extension" >nul || goto :fail
xcopy /e /i /q /y "%SDM_BUILD%\extension-firefox" "%SDM_DIST%\ScarletDM\extension-firefox" >nul || goto :fail
copy /y README.md "%SDM_DIST%\ScarletDM\" >nul
copy /y LICENSE "%SDM_DIST%\ScarletDM\LICENSE.txt" >nul
copy /y THIRD_PARTY_NOTICES.md "%SDM_DIST%\ScarletDM\" >nul

if not exist "%SDM_DIST%\ScarletDM\ScarletDM.exe" goto :fail
echo.
echo OK: %SDM_DIST%\ScarletDM\ScarletDM.exe

if /i "%~1"=="release" (
  %PY% tools\make_release.py "%SDM_DIST%\ScarletDM" "%SDM_RELEASE%" || goto :fail
  echo OK: pasta %SDM_RELEASE% pronta para publicar.
)
exit /b 0

:fail
echo.
echo FALHOU - veja as mensagens acima.
exit /b 1
