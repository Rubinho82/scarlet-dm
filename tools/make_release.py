"""Monta a pasta release/ para distribuir o Scarlet DM.

  ScarletDM-<v>-Setup.exe        instalador Inno Setup (atalhos, iniciar com o Windows, desinstalador)
  ScarletDM-<v>-Portable.zip     versão portátil: descompacte e rode (dados ficam na própria pasta)
  ScarletDM-<v>-source.zip       código-fonte (edição open source, licença MIT)
  scarlet-dm-chromium.zip        extensão para Chrome Web Store / Edge Add-ons / Opera
  scarlet-dm-firefox.zip         extensão para addons.mozilla.org
  SHA256SUMS.txt                 somas para conferir os downloads
  site/                          página pronta para subir: index.html + assets/ + downloads/ (os arquivos acima)

Uso: python tools/make_release.py [pasta_do_app] [pasta_de_saida]
"""
import hashlib
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from scarlet import VERSION  # noqa: E402
import build_inno  # noqa: E402
import package_extension  # noqa: E402

SOURCE_FILES = ["main.py", "requirements.txt", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "build_exe.bat",
                "run.bat", "criar_atalho.bat", ".gitignore"]
SOURCE_DIRS = ["scarlet", "extension", "tools", "installer", "assets", "site", "tests", "packaging", ".github"]
SKIP_DIRS = {"__pycache__", ".git", "build", "dist", "release"}


def zip_tree(z, src, arc_root):
    for base, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(base, f)
            z.write(full, (arc_root + "/" + os.path.relpath(full, src).replace(os.sep, "/")).lstrip("/"))


def portable_zip(app_dir, dest):
    top = f"ScarletDM-{VERSION}-Portable"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        zip_tree(z, app_dir, top)
        z.writestr(top + "/portable.ini",
                   "; Com este arquivo ao lado do ScarletDM.exe, o Scarlet DM guarda lista e configurações\r\n"
                   "; na subpasta data (modo portátil, bom para pendrive). Apague-o para usar o %APPDATA%.\r\n")


def source_zip(dest):
    top = f"ScarletDM-{VERSION}-source"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in SOURCE_FILES:
            p = os.path.join(ROOT, f)
            if os.path.isfile(p):
                z.write(p, f"{top}/{f}")
        for d in SOURCE_DIRS:
            p = os.path.join(ROOT, d)
            if os.path.isdir(p):
                zip_tree(z, p, f"{top}/{d}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(app_dir, out):
    os.makedirs(out, exist_ok=True)
    if build_inno.main(app_dir, out) != 0:
        return 1
    print("versão portátil…")
    portable_zip(app_dir, os.path.join(out, f"ScarletDM-{VERSION}-Portable.zip"))
    print("código-fonte…")
    source_zip(os.path.join(out, f"ScarletDM-{VERSION}-source.zip"))
    print("extensões…")
    package_extension.main(out)
    names = sorted(n for n in os.listdir(out) if n.endswith((".exe", ".zip", ".AppImage", ".dmg", ".tar.gz")))
    with open(os.path.join(out, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n") as f:
        for n in names:
            f.write(f"{sha256(os.path.join(out, n))}  {n}\n")
    shutil.copy2(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), os.path.join(out, "THIRD_PARTY_NOTICES.md"))
    site_bundle(out, names + ["SHA256SUMS.txt", "THIRD_PARTY_NOTICES.md"])
    for n in names:
        print(f"  {n}  ({os.path.getsize(os.path.join(out, n)) / 1048576:.1f} MB)")
    print("  site/ pronto para subir (index.html + downloads/)")
    return 0


def site_bundle(out, files):
    """release/site = o site + downloads/ com os pacotes (links físicos quando dá, para não ocupar espaço de novo)."""
    dest = os.path.join(out, "site")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(os.path.join(ROOT, "site"), dest)
    dl = os.path.join(dest, "downloads")
    os.makedirs(dl, exist_ok=True)
    for n in files:
        src, dst = os.path.join(out, n), os.path.join(dl, n)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(os.path.abspath(a[0]) if a else os.path.join(ROOT, "dist", "ScarletDM"),
                  os.path.abspath(a[1]) if len(a) > 1 else os.path.join(ROOT, "release")))
