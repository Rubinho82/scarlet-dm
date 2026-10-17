"""Gera release/ScarletDM-<versão>-Setup.exe a partir da pasta já montada pelo build_exe.bat (dist/ScarletDM).

Uso: python tools/build_installer.py [pasta_do_app] [pasta_de_saida]
O Setup.exe é um executável único: leva o app compactado e uma tela de instalação no mesmo tema do Scarlet.
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scarlet import APP_NAME, VERSION  # noqa: E402

# Nada disso é usado pela tela de instalação (só QtCore/QtGui/QtWidgets)
EXCLUDES = ["PySide6.QtNetwork", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSvg",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf", "libtorrent", "requests",
            "urllib3", "cryptography", "yt_dlp", "tkinter", "numpy", "PIL", "unittest", "pydoc", "pandas",
            "matplotlib", "IPython", "Crypto", "Cryptodome", "lib2to3", "xmlrpc"]
# (o plugin de SVG fica: o tema desenha as caixas de seleção com SVG)
DROP_BINARIES = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6opengl", "qt6virtualkeyboard", "qt6network",
                 "qtvirtualkeyboardplugin", "qpdf", "qdirect2d", "qminimal", "qoffscreen", "qtuiotouchplugin",
                 "avcodec", "avformat", "avutil", "swscale", "swresample", "qt6multimedia", "ffmpegmediaplugin",
                 "libcrypto", "libssl", "qopensslbackend", "qschannelbackend", "qcertonlybackend",
                 "qnetworklistmanager")


def version_file(path, name, description):
    v = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{description}'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def make_payload(app_dir, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, dirs, files in os.walk(app_dir):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, app_dir).replace(os.sep, "/"))
    return dest


def main(app_dir, out_dir):
    if not os.path.isfile(os.path.join(app_dir, "ScarletDM.exe")):
        print("Rode antes o build_exe.bat (não achei", os.path.join(app_dir, "ScarletDM.exe"), ")")
        return 1
    work = os.path.join(os.path.abspath(os.environ.get("SDM_BUILD") or os.path.join(ROOT, "build")), "installer")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)
    print("compactando o app…")
    payload = make_payload(app_dir, os.path.join(work, "payload", "ScarletDM.zip"))
    name = f"ScarletDM-{VERSION}-Setup"
    vfile = version_file(os.path.join(work, "version.txt"), name, f"Instalador do {APP_NAME}")
    spec = os.path.join(work, "setup.spec")
    with open(spec, "w", encoding="utf-8") as f:
        f.write(f"""# gerado por tools/build_installer.py
a = Analysis([{os.path.join(ROOT, 'installer', 'setup.py')!r}], pathex=[{ROOT!r}],
             datas=[({os.path.dirname(payload)!r}, 'payload'),
                    ({os.path.join(ROOT, 'scarlet', 'locales')!r}, 'scarlet/locales')],
             excludes={EXCLUDES!r})
drop = {DROP_BINARIES!r}
a.binaries = [b for b in a.binaries if not any(d in b[0].lower().replace('\\\\', '/').split('/')[-1] for d in drop)]
a.datas = [d for d in a.datas if not (d[0].lower().startswith(('pyside6/translations', 'pyside6\\\\translations'))
                                      and 'qtbase_' not in d[0].lower())]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name={name!r}, console=False, upx=False,
          icon={os.path.join(ROOT, 'assets', 'app.ico')!r}, version={vfile!r})
""")
    print("gerando o Setup.exe…")
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--distpath", out_dir, "--workpath", os.path.join(work, "tmp"), spec])
    exe = os.path.join(out_dir, name + ".exe")
    if r.returncode != 0 or not os.path.isfile(exe):
        print("FALHOU")
        return 1
    print(f"ok: {exe} ({os.path.getsize(exe) / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--version-file"]:        # usado pelo build_exe.bat para o ScarletDM.exe
        version_file(a[1], "ScarletDM", f"{APP_NAME} - gerenciador de downloads")
        sys.exit(0)
    sys.exit(main(os.path.abspath(a[0]) if a else os.path.join(ROOT, "dist", "ScarletDM"),
                  os.path.abspath(a[1]) if len(a) > 1 else os.path.join(ROOT, "release")))
