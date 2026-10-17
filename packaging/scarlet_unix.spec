# PyInstaller: Scarlet DM para Linux e macOS (o Windows usa o build_exe.bat).
# Uso: pyinstaller --noconfirm packaging/scarlet_unix.spec
import os
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from scarlet import VERSION  # noqa: E402

IS_MAC = sys.platform == "darwin"

binaries = []
try:
    binaries += collect_dynamic_libs("libtorrent")
except Exception:
    pass

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=[(os.path.join(ROOT, "assets"), "assets"),
           (os.path.join(ROOT, "scarlet", "locales"), "scarlet/locales"),
           (os.path.join(ROOT, "scarlet", "assets"), "scarlet/assets")],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtNetwork", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
                   "cryptography.hazmat.primitives.ciphers", "libtorrent"],
    excludes=["tkinter", "numpy", "matplotlib", "PIL", "pandas", "IPython", "Crypto", "Cryptodome"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ScarletDM", console=False, upx=False,
          icon=os.path.join(ROOT, "assets", "app.icns" if IS_MAC else "app.png"))
coll = COLLECT(exe, a.binaries, a.datas, name="ScarletDM", upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Scarlet DM.app",
        icon=os.path.join(ROOT, "assets", "app.icns"),
        bundle_identifier="com.scarletdm.app",
        version=VERSION,
        info_plist={
            "CFBundleName": "Scarlet DM",
            "CFBundleDisplayName": "Scarlet DM",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
            # abre links magnet: e arquivos .torrent
            "CFBundleURLTypes": [{"CFBundleURLName": "Magnet link", "CFBundleURLSchemes": ["magnet"]}],
            "CFBundleDocumentTypes": [{"CFBundleTypeName": "BitTorrent file", "CFBundleTypeRole": "Viewer",
                                       "CFBundleTypeExtensions": ["torrent"], "LSHandlerRank": "Alternate"}],
        },
    )
