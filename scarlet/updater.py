"""Atualização do próprio Scarlet DM pelos Releases do GitHub.

check() descobre se há versão nova; prepare() baixa o pacote certo para o sistema e confere o SHA-256
(SHA256SUMS.txt do mesmo lançamento); apply() troca a versão e reabre o app:
  Windows instalado  -> roda o Setup.exe novo em modo silencioso na mesma pasta (/UPDATE=1 o faz reabrir o app)
  Linux AppImage     -> troca o arquivo .AppImage e reabre
  macOS              -> abre o .dmg baixado (é só arrastar para Aplicativos)
  portátil/código    -> abre a página de downloads
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from . import VERSION

REPO = "Rubinho82/scarlet-dm"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
SITE = "https://rubinho82.github.io/scarlet-dm/"
UA = f"ScarletDM/{VERSION} (+https://github.com/{REPO})"


def parse_version(v):
    out = []
    for part in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple((out + [0, 0, 0])[:3])


def is_newer(remote, local=VERSION):
    return parse_version(remote) > parse_version(local)


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(timeout=15):
    """{'version', 'notes', 'page', 'assets': {nome: url}} do último lançamento, ou None se não der para saber."""
    data = json.loads(_get(API, timeout).decode("utf-8"))
    if data.get("draft") or data.get("prerelease"):
        return None
    return {"version": str(data.get("tag_name", "")).lstrip("vV"), "notes": data.get("body") or "",
            "page": data.get("html_url") or PAGE,
            "assets": {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}}


# ------------------------------------------------------------------ como este app foi instalado
def install_kind():
    if not getattr(sys, "frozen", False):
        return "source"
    exe_dir = os.path.dirname(sys.executable)
    if os.name == "nt":
        if os.path.isfile(os.path.join(exe_dir, "portable.ini")):
            return "portable"
        if any(f.lower().startswith("unins") and f.lower().endswith(".exe") for f in os.listdir(exe_dir)):
            return "windows"
        return "portable"
    if sys.platform == "darwin":
        return "mac"
    return "appimage" if os.environ.get("APPIMAGE") else "linux"


def asset_for(info, kind=None):
    """Nome do arquivo do lançamento que serve para esta instalação (ou None = mandar para a página)."""
    kind = kind or install_kind()
    v = info["version"]
    arm = platform.machine().lower() in ("arm64", "aarch64")
    name = {"windows": f"ScarletDM-{v}-Setup.exe",
            "mac": f"ScarletDM-{v}-macos-{'arm64' if arm else 'x64'}.dmg",
            "appimage": f"ScarletDM-{v}-linux-{'arm64' if arm else 'x64'}.AppImage"}.get(kind)
    return name if name and name in info["assets"] else None


def can_auto_update(info):
    return asset_for(info) is not None


# ------------------------------------------------------------------ baixar e conferir
def prepare(info, progress=None, cancelled=lambda: False):
    """Baixa o pacote para uma pasta temporária e confere o SHA-256. Devolve o caminho do arquivo."""
    name = asset_for(info)
    if not name:
        raise RuntimeError("no-asset")
    sums = {}
    if "SHA256SUMS.txt" in info["assets"]:
        for line in _get(info["assets"]["SHA256SUMS.txt"]).decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0].lower()
    if name not in sums:
        raise RuntimeError("no-checksum")       # sem soma para conferir, não instala nada
    dest = os.path.join(tempfile.mkdtemp(prefix="scarletdm-update-"), name)
    req = urllib.request.Request(info["assets"][name], headers={"User-Agent": UA})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancelled():
                raise RuntimeError("cancelled")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if h.hexdigest().lower() != sums[name]:
        os.remove(dest)
        raise RuntimeError("bad-checksum")
    return dest


# ------------------------------------------------------------------ instalar
def apply(path, lang=""):
    """Começa a troca de versão. True = o app deve se fechar agora (Windows/Linux); False = continua aberto."""
    kind = install_kind()
    if kind == "windows":
        app_dir = os.path.dirname(sys.executable)
        args = [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE=1",
                f"/DIR={app_dir}"]
        if lang:
            args.append(f"/LANG={lang}")
        subprocess.Popen(args, close_fds=True, creationflags=0x00000008 | 0x00000200)   # desacoplado do app
        return True
    if kind == "appimage":
        target = os.environ["APPIMAGE"]
        os.chmod(path, 0o755)
        tmp = target + ".new"
        shutil.move(path, tmp)
        os.replace(tmp, target)
        subprocess.Popen([target], close_fds=True, start_new_session=True)
        return True
    if kind == "mac":
        subprocess.Popen(["open", path])
    return False
