#!/usr/bin/env bash
# Gera o Scarlet DM para Linux ou macOS (rode no próprio sistema; o GitHub Actions faz os dois sozinho).
#   Linux: release/ScarletDM-<v>-linux-<arq>.AppImage  e  .tar.gz
#   macOS: release/ScarletDM-<v>-macos-<arq>.dmg        (app "Scarlet DM.app")
# Uso: bash tools/build_unix.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${PYTHON:-python3}"
VERSION="$($PY -c 'import scarlet; print(scarlet.VERSION)')"
ARCH="$(uname -m)"; [ "$ARCH" = "aarch64" ] && ARCH="arm64"; [ "$ARCH" = "x86_64" ] && ARCH="x64"
OUT="${SDM_RELEASE:-$ROOT/release}"
WORK="${SDM_BUILD:-$ROOT/build}"
mkdir -p "$OUT" "$WORK"

$PY -c "import PySide6, requests, cryptography, PyInstaller" 2>/dev/null || \
  $PY -m pip install -q -r requirements.txt pyinstaller
$PY -c "import libtorrent" 2>/dev/null || echo "AVISO: libtorrent ausente - sai sem torrent/magnet."

$PY tools/package_extension.py "$WORK/extensions"
$PY -m PyInstaller --noconfirm --clean --distpath "$WORK/dist" --workpath "$WORK/pyi" packaging/scarlet_unix.spec

if [ "$(uname)" = "Darwin" ]; then
  APP="$WORK/dist/Scarlet DM.app"
  RES="$APP/Contents/Resources"
  cp -R extension "$RES/extension"
  cp -R "$WORK/extension-firefox" "$RES/extension-firefox"
  cp LICENSE "$RES/LICENSE.txt"; cp THIRD_PARTY_NOTICES.md README.md "$RES/"
  # assinatura ad hoc: obrigatória no Apple Silicon (sem conta paga da Apple; ver README sobre notarização)
  codesign --force --deep --sign - "$APP"
  "$APP/Contents/MacOS/ScarletDM" --selftest --out "$WORK/selftest.json" || { cat "$WORK/selftest.json"; exit 1; }
  DMG="$OUT/ScarletDM-$VERSION-macos-$ARCH.dmg"
  STAGE="$WORK/dmg"; rm -rf "$STAGE"; mkdir -p "$STAGE"
  cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
  rm -f "$DMG"
  hdiutil create -volname "Scarlet DM" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
  echo "OK: $DMG"
else
  DIST="$WORK/dist/ScarletDM"
  cp -R extension "$DIST/extension"
  cp -R "$WORK/extension-firefox" "$DIST/extension-firefox"
  cp LICENSE "$DIST/LICENSE.txt"; cp THIRD_PARTY_NOTICES.md README.md "$DIST/"
  QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" SCARLETDM_DATA="$WORK/selftest-data" \
    "$DIST/ScarletDM" --selftest --out "$WORK/selftest.json" || { cat "$WORK/selftest.json"; exit 1; }
  tar -C "$WORK/dist" -czf "$OUT/ScarletDM-$VERSION-linux-$ARCH.tar.gz" ScarletDM

  # AppImage: um arquivo só, roda em quase toda distro (Ubuntu, Fedora, Mint, Arch, Debian…)
  APPDIR="$WORK/ScarletDM.AppDir"; rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr"
  cp -R "$DIST" "$APPDIR/usr/lib-scarletdm"
  cp assets/scarletdm.png "$APPDIR/scarletdm.png"
  mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"; cp assets/scarletdm.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
  cat > "$APPDIR/scarletdm.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Scarlet DM
Comment=Download manager
Exec=ScarletDM %u
Icon=scarletdm
Terminal=false
Categories=Network;FileTransfer;
MimeType=x-scheme-handler/magnet;application/x-bittorrent;
StartupWMClass=ScarletDM
EOF
  cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib-scarletdm/ScarletDM" "$@"
EOF
  chmod +x "$APPDIR/AppRun"
  TOOL="$WORK/appimagetool"
  if [ ! -x "$TOOL" ]; then
    AT_ARCH="$(uname -m)"
    curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$AT_ARCH.AppImage"
    chmod +x "$TOOL"
  fi
  APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$(uname -m)" "$TOOL" --no-appstream "$APPDIR" "$OUT/ScarletDM-$VERSION-linux-$ARCH.AppImage"
  echo "OK: $OUT/ScarletDM-$VERSION-linux-$ARCH.AppImage"
fi
