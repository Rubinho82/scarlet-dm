"""Prepara a extensão para os navegadores.

Gera:
  build/extension-firefox/        cópia de extension/ com o manifest do Firefox (background.scripts + id gecko)
  <saida>/scarlet-dm-chromium.zip pacote para Chrome Web Store / Edge Add-ons / Opera (mesmo código)
  <saida>/scarlet-dm-firefox.zip  pacote para addons.mozilla.org (a Mozilla assina e devolve o .xpi)

Uso: python tools/package_extension.py [pasta_de_saida]   (padrão: release)
"""
import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "extension")
GECKO_ID = "scarlet-dm@scarletdm.app"


def firefox_manifest(m):
    m = dict(m)
    m["background"] = {"scripts": ["background.js"]}
    m["browser_specific_settings"] = {"gecko": {
        "id": GECKO_ID,
        "strict_min_version": "115.0",
        "data_collection_permissions": {"required": ["none"]},
    }}
    return m


def zip_dir(src, dest):
    if os.path.exists(dest):
        os.remove(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(src):
            for f in sorted(files):
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, src).replace(os.sep, "/"))


def main(out_dir):
    manifest = json.load(open(os.path.join(SRC, "manifest.json"), encoding="utf-8"))
    ff = os.path.join(os.path.abspath(os.environ.get("SDM_BUILD") or os.path.join(ROOT, "build")), "extension-firefox")
    if os.path.isdir(ff):
        shutil.rmtree(ff)
    shutil.copytree(SRC, ff)
    with open(os.path.join(ff, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(firefox_manifest(manifest), f, ensure_ascii=False, indent=2)
    os.makedirs(out_dir, exist_ok=True)
    zip_dir(SRC, os.path.join(out_dir, "scarlet-dm-chromium.zip"))
    zip_dir(ff, os.path.join(out_dir, "scarlet-dm-firefox.zip"))
    print("ok:", ff, "e", out_dir)
    return ff


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "release")))
