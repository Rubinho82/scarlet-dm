"""Componentes externos baixados sob demanda para <dados do app>/bin (nada é instalado no sistema).

- mecanismo de vídeos (yt-dlp): vídeos/músicas de sites; atualizado com frequência
- ffmpeg/ffprobe: junta áudio+vídeo, converte para MP3, gera miniaturas
- deno: executa o JavaScript que o YouTube exige (só se não houver Node/Deno/Bun no PC)
"""
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from ..i18n import _
from ..util import EXE, IS_MAC, IS_WIN, app_data_dir

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ARM = platform.machine().lower() in ("arm64", "aarch64", "armv8", "armv8l")
_GH = "https://github.com/{}/releases/latest/download/{}"
_FB = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"

# executáveis oficiais por sistema (o yt-dlp e o Deno publicam binários prontos para cada um)
if IS_WIN:
    YTDLP_URL = _GH.format("yt-dlp/yt-dlp", "yt-dlp.exe")
    FFMPEG_URL = _FB + "ffmpeg-master-latest-win64-gpl-shared.zip"
    DENO_URL = _GH.format("denoland/deno", "deno-x86_64-pc-windows-msvc.zip")
elif IS_MAC:
    YTDLP_URL = _GH.format("yt-dlp/yt-dlp", "yt-dlp_macos")                    # universal (Intel + Apple Silicon)
    # builds estáticos para macOS listados em ffmpeg.org (o projeto FFmpeg-Builds não tem macOS)
    FFMPEG_URL = f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{'arm64' if ARM else 'amd64'}/release/"
    DENO_URL = _GH.format("denoland/deno", f"deno-{'aarch64' if ARM else 'x86_64'}-apple-darwin.zip")
else:
    YTDLP_URL = _GH.format("yt-dlp/yt-dlp", "yt-dlp_linux_aarch64" if ARM else "yt-dlp_linux")
    FFMPEG_URL = _FB + f"ffmpeg-master-latest-{'linuxarm64' if ARM else 'linux64'}-gpl.tar.xz"
    DENO_URL = _GH.format("denoland/deno", f"deno-{'aarch64' if ARM else 'x86_64'}-unknown-linux-gnu.zip")
YTDLP_NAME = "yt-dlp" + EXE


def _make_executable(path):
    if not IS_WIN:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if IS_MAC:   # binário baixado por nós (não pelo navegador): tira a quarentena para o Gatekeeper não travar
            subprocess.run(["xattr", "-d", "com.apple.quarantine", path], capture_output=True)


def bin_dir():
    d = os.path.join(app_data_dir(), "bin")
    os.makedirs(d, exist_ok=True)
    return d


def _env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# ------------------------------------------------------------------ localizar
def ytdlp_command():
    exe = os.path.join(bin_dir(), YTDLP_NAME)
    if os.path.isfile(exe):
        return [exe]
    if not getattr(sys, "frozen", False):
        try:
            import importlib.util
            if importlib.util.find_spec("yt_dlp") is not None:
                py = sys.executable
                if os.path.basename(py).lower() == "pythonw.exe":
                    cand = os.path.join(os.path.dirname(py), "python.exe")
                    py = cand if os.path.exists(cand) else py
                return [py, "-m", "yt_dlp"]
        except Exception:
            pass
    found = shutil.which("yt-dlp")
    return [found] if found else None


def ffmpeg_path(configured=""):
    from ..util import find_ffmpeg
    return find_ffmpeg(configured)


def ffprobe_path(configured=""):
    ff = ffmpeg_path(configured)
    if ff:
        cand = os.path.join(os.path.dirname(ff), "ffprobe" + EXE)
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffprobe") or ""


def js_runtime():
    """(nome, caminho) do runtime JavaScript disponível, ou (None, None)."""
    for name in ("deno", "node", "bun"):
        p = shutil.which(name)
        if p:
            return name, p
    local = os.path.join(bin_dir(), "deno" + EXE)
    if os.path.isfile(local):
        return "deno", local
    return None, None


def js_runtime_args():
    name, path = js_runtime()
    if not name:
        return []
    return ["--js-runtimes", f"{name}:{path}"]


# ------------------------------------------------------------------ versões
def _run_version(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW,
                           env=_env(), encoding="utf-8", errors="replace")
        out = (p.stdout or p.stderr).strip().splitlines()
        return out[0] if out else ""
    except Exception:
        return ""


def ytdlp_version():
    cmd = ytdlp_command()
    if not cmd:
        return None
    v = _run_version(cmd + ["--version"])
    return v.splitlines()[-1] if v else None


def ffmpeg_version():
    ff = ffmpeg_path()
    if not ff:
        return None
    v = _run_version([ff, "-version"])
    parts = v.split()
    return parts[2] if len(parts) > 2 else (v or None)


def js_version():
    name, path = js_runtime()
    if not name:
        return None
    v = _run_version([path, "--version"])
    return f"{name} {v.replace('deno ', '').split()[0] if v else ''}".strip()


# ------------------------------------------------------------------ instalar
def _download(url, dest, progress=None):
    import requests
    tmp = dest + ".download"
    with requests.get(url, stream=True, timeout=(15, 120), allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1024 * 512):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done, total)
    os.replace(tmp, dest)
    return dest


def install_ytdlp(progress=None):
    """No .exe (ou quando já usa o binário) baixa o oficial; rodando pelo Python, atualiza com pip."""
    # Sempre o executável oficial: traz o próprio Python e o resolvedor do YouTube (independe do Python do PC).
    exe = os.path.join(bin_dir(), YTDLP_NAME)
    _download(YTDLP_URL, exe, progress)
    if os.path.getsize(exe) < 1_000_000:
        os.remove(exe)
        raise RuntimeError(_("Download do componente veio incompleto"))
    _make_executable(exe)
    return ytdlp_version()


def _extract(archive, wanted, dest_dir):
    """Extrai do .zip/.tar.xz os arquivos cujo nome (sem pasta) passa no filtro `wanted(nome)`."""
    n = 0

    def put(name, src):
        nonlocal n
        target = os.path.join(dest_dir, name)
        with open(target + ".tmp", "wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        os.replace(target + ".tmp", target)
        _make_executable(target)
        n += 1

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = os.path.basename(info.filename)
                if name and not info.is_dir() and wanted(name):
                    with z.open(info) as src:
                        put(name, src)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                name = os.path.basename(m.name)
                if name and m.isfile() and wanted(name):
                    put(name, t.extractfile(m))
    return n


def install_ffmpeg(progress=None):
    d = bin_dir()
    names = ("ffmpeg" + EXE, "ffprobe" + EXE)
    parts = [(FFMPEG_URL + "ffmpeg.zip", "ffmpeg"), (FFMPEG_URL + "ffprobe.zip", "ffprobe")] if IS_MAC \
        else [(FFMPEG_URL, "ffmpeg")]
    n = 0
    for url, tag in parts:
        tmp = os.path.join(tempfile.gettempdir(), f"scarlet-{tag}-{os.getpid()}.pkg")
        try:
            _download(url, tmp, progress)
            n += _extract(tmp, lambda nm: nm.lower() in names or (IS_WIN and nm.lower().endswith(".dll")), d)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if not os.path.isfile(os.path.join(d, names[0])) or n < 2:
        raise RuntimeError(_("Pacote do ffmpeg inválido"))
    return ffmpeg_version()


def install_deno(progress=None):
    d = bin_dir()
    tmp = os.path.join(tempfile.gettempdir(), "scarlet-deno.zip")
    try:
        _download(DENO_URL, tmp, progress)
        _extract(tmp, lambda nm: nm.lower() == "deno" + EXE, d)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if not os.path.isfile(os.path.join(d, "deno" + EXE)):
        raise RuntimeError(_("Pacote do Deno inválido"))
    return js_version()


def needs_js(url):
    low = url.lower()
    return "youtube.com" in low or "youtu.be" in low
