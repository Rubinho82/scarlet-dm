"""Funções utilitárias: caminhos, nomes de arquivo, formatação."""
import os
import re
import sys
import uuid
import shutil
import mimetypes
import urllib.parse
from email.header import decode_header
from http.server import ThreadingHTTPServer

from . import APP_ID, VERSION

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
EXE = ".exe" if IS_WIN else ""          # sufixo dos executáveis (ffmpeg.exe / ffmpeg)

# User-Agent honesto: fingir ser Chrome com a assinatura TLS do Python faz CDNs com proteção anti-bot
# (ex.: Hetzner) derrubarem a conexão. Links vindos do navegador usam o UA real do navegador.
DEFAULT_UA = f"Mozilla/5.0 (compatible; ScarletDM/{VERSION}; +Windows)"

CATEGORIES = {
    "video": {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "3gp", "ts", "m2ts", "vob", "ogv"},
    "audio": {"mp3", "aac", "flac", "wav", "ogg", "opus", "m4a", "wma", "alac", "aiff", "mka"},
    "document": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "txt", "rtf", "epub", "mobi", "csv", "md"},
    "archive": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "zst", "tgz", "cab", "lz", "lzma"},
    "program": {"exe", "msi", "msix", "appx", "bat", "cmd", "apk", "dmg", "pkg", "deb", "rpm", "appimage", "jar", "iso", "img"},
    "image": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tif", "tiff", "ico", "heic", "avif", "raw"},
}

CATEGORY_LABELS = {
    "video": "Vídeo",
    "audio": "Música",
    "document": "Documentos",
    "archive": "Compactados",
    "program": "Programas",
    "image": "Imagens",
    "torrent": "Torrent",
    "other": "Outros",
}

# Extensões que o monitor de área de transferência considera "baixáveis".
DOWNLOADABLE_EXTS = set().union(*CATEGORIES.values()) | {"torrent", "m3u8", "bin", "dat"}


def portable_dir():
    """Modo portátil (pendrive): com um portable.ini ao lado do ScarletDM.exe, os dados ficam em ./data."""
    if getattr(sys, "frozen", False) and not IS_MAC:
        here = os.path.dirname(sys.executable)
        if os.path.isfile(os.path.join(here, "portable.ini")):
            return os.path.join(here, "data")
    return ""


def app_data_dir():
    d = os.environ.get("SCARLETDM_DATA") or portable_dir()
    if not d:
        if IS_WIN:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
        elif IS_MAC:
            base = os.path.expanduser("~/Library/Application Support")
        else:   # Linux e outros: padrão XDG (~/.local/share)
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        d = os.path.join(base, APP_ID)
    os.makedirs(d, exist_ok=True)
    return d


def default_download_dir():
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

            g = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")  # FOLDERID_Downloads
            guid = GUID(g.fields[0], g.fields[1], g.fields[2],
                        (wintypes.BYTE * 8)(*g.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                if path:
                    return path
        except Exception:
            pass
    elif IS_LINUX:
        try:   # pasta "Downloads" traduzida (ex.: ~/Transferências) segundo o xdg-user-dirs
            import subprocess
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out and out != os.path.expanduser("~") and os.path.isdir(out):
                return out
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize_filename(name, fallback="download"):
    name = _INVALID.sub("_", name or "").strip().rstrip(". ")
    if not name:
        name = fallback
    stem, ext = os.path.splitext(name)
    if stem.upper() in _RESERVED:
        name = "_" + name
    if len(name) > 200:
        name = stem[: 200 - len(ext)] + ext
    return name


def filename_from_content_disposition(cd):
    if not cd:
        return None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", cd, re.I)
    if m:
        enc = (m.group(1) or "utf-8").strip() or "utf-8"
        raw = m.group(2).strip().strip('"')
        try:
            return urllib.parse.unquote(raw, encoding=enc, errors="replace")
        except LookupError:
            return urllib.parse.unquote(raw)
    m = re.search(r'filename\s*=\s*"((?:\\.|[^"\\])*)"', cd, re.I)
    if m:
        name = m.group(1).replace('\\"', '"')
    else:
        m = re.search(r"filename\s*=\s*([^;]+)", cd, re.I)
        if not m:
            return None
        name = m.group(1).strip()
    if name.startswith("=?"):
        try:
            parts = decode_header(name)
            name = "".join(p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p for p, c in parts)
        except Exception:
            pass
    else:
        # http.client decodifica cabeçalhos como latin-1; muitos servidores mandam UTF-8 cru.
        try:
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def filename_from_url(url):
    p = urllib.parse.urlsplit(url)
    base = urllib.parse.unquote(p.path.rsplit("/", 1)[-1])
    return base or p.hostname or "download"


def guess_extension(content_type):
    if not content_type:
        return ""
    ct = content_type.split(";")[0].strip().lower()
    if ct in ("application/octet-stream", "binary/octet-stream", "text/plain"):
        return ""
    return mimetypes.guess_extension(ct) or ""


def ext_of(name):
    return os.path.splitext(name or "")[1].lstrip(".").lower()


def category_for(name):
    e = ext_of(name)
    for cat, exts in CATEGORIES.items():
        if e in exts:
            return cat
    return "other"


def looks_like_url(text):
    t = (text or "").strip()
    return bool(re.match(r"^(https?|ftp)://\S+$", t, re.I)) or t.lower().startswith("magnet:?")


def extract_urls(text):
    """Extrai URLs http(s)/ftp e magnets de um texto qualquer, sem duplicatas e na ordem."""
    found = re.findall(r"(?:https?|ftp)://[^\s<>\"']+|magnet:\?[^\s<>\"']+", text or "", re.I)
    out, seen = [], set()
    for u in found:
        u = u.rstrip(").,;]")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_downloadable_url(url):
    if url.lower().startswith("magnet:?"):
        return True
    return ext_of(filename_from_url(url)) in DOWNLOADABLE_EXTS


def unique_path(path, taken=()):
    """Devolve um caminho livre: 'nome (1).ext', 'nome (2).ext'..."""
    taken = {os.path.normcase(t) for t in taken}

    def free(p):
        return not os.path.exists(p) and os.path.normcase(p) not in taken

    if free(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{stem} ({i}){ext}"
        if free(cand):
            return cand
        i += 1


def _fmt_num(v, decimals):
    s = f"{v:.{decimals}f}"
    from .i18n import current
    return s if current() in ("en", "zh_CN", "ja", "ko") else s.replace(".", ",")


def format_size(n):
    if n is None or n < 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    if i == 0:
        return f"{int(v)} B"
    return f"{_fmt_num(v, 2 if v < 10 else 1 if v < 100 else 0)} {units[i]}"


def format_speed(bps):
    if not bps or bps < 1:
        return ""
    return format_size(bps) + "/s"


def format_eta(seconds):
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def parse_speed(text):
    """'2 MB/s', '512k', '1,5M' -> bytes/s. Vazio/0 -> 0 (sem limite)."""
    t = (text or "").strip().lower().replace(",", ".").replace("/s", "").replace("b", "")
    if not t:
        return 0
    mult = 1
    if t[-1] in "kmg":
        mult = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[t[-1]]
        t = t[:-1]
    try:
        return int(float(t.strip()) * mult)
    except ValueError:
        return 0


def free_space(path):
    try:
        while path and not os.path.exists(path):
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
        return shutil.disk_usage(path).free
    except Exception:
        return -1


def find_ffmpeg(configured=""):
    if configured and os.path.isfile(configured):
        return configured
    here = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__))
    name = "ffmpeg" + EXE
    for cand in (os.path.join(here, name), os.path.join(here, "bin", name),
                 os.path.join(app_data_dir(), "bin", name)):
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffmpeg") or ""


def set_sparse(path):
    """Marca o arquivo como esparso no NTFS: gravar em qualquer posição não força
    o Windows a preencher com zeros tudo que vem antes (o FDM pré-aloca pelo mesmo motivo)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                        wintypes.LPVOID]
        k32.DeviceIoControl.restype = wintypes.BOOL
        with open(path, "r+b") as f:
            h = msvcrt.get_osfhandle(f.fileno())
            br = wintypes.DWORD()
            k32.DeviceIoControl(h, 0x000900C4, None, 0, None, 0, ctypes.byref(br), None)
    except Exception:
        pass


def set_file_size(path, size):
    """Define o tamanho do arquivo sem escrever nada.

    No Windows o truncate() do Python (CRT _chsize) PREENCHE com zeros ao aumentar: 10 GB levam ~50 s
    e ocupam o disco todo, anulando o arquivo esparso. SetEndOfFile só mexe nos metadados.
    """
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                             ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
            k32.SetFilePointerEx.restype = wintypes.BOOL
            k32.SetEndOfFile.argtypes = [wintypes.HANDLE]
            k32.SetEndOfFile.restype = wintypes.BOOL
            with open(path, "r+b") as f:
                h = msvcrt.get_osfhandle(f.fileno())
                if not k32.SetFilePointerEx(h, int(size), None, 0) or not k32.SetEndOfFile(h):
                    raise ctypes.WinError()
            return
        except OSError:
            raise
        except Exception:
            pass
    with open(path, "r+b") as f:
        f.truncate(size)


def mark_of_the_web(path, url="", referer=""):
    """Grava a 'marca da Web' (Zone.Identifier), como navegadores fazem: o Windows/SmartScreen e o
    Office tratam o arquivo como vindo da internet. É a opção “Marcar arquivos baixados” do FDM.
    No macOS é o atributo de quarentena (o Gatekeeper confere apps baixados); no Linux, o padrão
    freedesktop user.xdg.origin.url (os gerenciadores de arquivos mostram de onde veio)."""
    if not os.path.isfile(path):
        return False
    if IS_MAC:
        try:
            import subprocess
            import time as _t
            value = f"0081;{int(_t.time()):x};Scarlet DM;"
            return subprocess.run(["xattr", "-w", "com.apple.quarantine", value, path],
                                  capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False
    if not IS_WIN:
        try:
            if url:
                os.setxattr(path, "user.xdg.origin.url", url.encode("utf-8"))
            if referer:
                os.setxattr(path, "user.xdg.referrer.url", referer.encode("utf-8"))
            return True
        except (OSError, AttributeError):
            return False
    lines = ["[ZoneTransfer]", "ZoneId=3"]
    if referer and referer.lower().startswith(("http://", "https://")):
        lines.append(f"ReferrerUrl={referer}")
    if url and url.lower().startswith(("http://", "https://", "ftp://")):
        lines.append(f"HostUrl={url}")
    try:
        with open(path + ":Zone.Identifier", "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except OSError:
        return False


_BATCH = re.compile(r"\[(\d+)-(\d+)\]|\[([a-zA-Z])-([a-zA-Z])\]")


def expand_batch(url, limit=5000):
    """'http://site/img[001-120].jpg' -> 120 links (mantém zeros à esquerda); também [a-z]."""
    m = _BATCH.search(url)
    if not m:
        return [url]
    if m.group(1) is not None:
        a, b = m.group(1), m.group(2)
        width = len(a) if a.startswith("0") and len(a) > 1 else 0
        lo, hi = int(a), int(b)
        step = 1 if hi >= lo else -1
        values = [str(i).zfill(width) for i in range(lo, hi + step, step)]
    else:
        lo, hi = ord(m.group(3)), ord(m.group(4))
        step = 1 if hi >= lo else -1
        values = [chr(c) for c in range(lo, hi + step, step)]
    out = []
    for v in values:
        for rest in expand_batch(url[:m.start()] + v + url[m.end():], limit):
            out.append(rest)
            if len(out) >= limit:
                return out
    return out


def trim_memory():
    """Devolve ao sistema a memória que o app não está usando agora (ao ir para a bandeja/minimizar)."""
    import gc
    gc.collect()
    if IS_LINUX:
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass
        return
    if not IS_WIN:
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.EmptyWorkingSet(ctypes.c_void_p(k32.GetCurrentProcess()))
    except Exception:
        pass


_awake_proc = None


def keep_awake(on):
    """Impede (ou volta a permitir) a suspensão do PC enquanto há downloads."""
    global _awake_proc
    if not IS_WIN:
        import subprocess
        if on and _awake_proc is None:
            if IS_MAC:     # caffeinate segura o sono enquanto o nosso processo existir
                cmd = ["caffeinate", "-i", "-w", str(os.getpid())]
            else:
                cmd = ["systemd-inhibit", "--what=sleep:idle", "--who=Scarlet DM", "--why=downloads",
                       "--mode=block", "sleep", "infinity"]
            try:
                _awake_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                _awake_proc = None
        elif not on and _awake_proc is not None:
            try:
                _awake_proc.terminate()
            except OSError:
                pass
            _awake_proc = None
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    except Exception:
        pass


def open_path(path):
    """Abre arquivo, pasta ou endereço (ms-settings:, https:) com o programa padrão do sistema."""
    if IS_WIN:
        os.startfile(path)  # noqa: S606 - abre com o programa associado, como o Explorer
    else:
        import subprocess
        subprocess.Popen(["open" if IS_MAC else "xdg-open", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal_in_folder(path):
    import subprocess
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if IS_WIN:
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif os.path.isdir(folder):
            os.startfile(folder)
    elif IS_MAC:
        subprocess.Popen(["open", "-R", path] if os.path.exists(path) else ["open", folder])
    else:
        # gerenciadores de arquivos modernos (Nautilus, Dolphin, Nemo…) selecionam o arquivo via D-Bus
        try:
            from urllib.parse import quote
            r = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                                "array:string:file://" + quote(os.path.abspath(path)), "string:"],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                return
        except Exception:
            pass
        subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class LocalHTTPServer(ThreadingHTTPServer):
    """Servidor HTTP que não divide a porta com outro programa.

    O padrão do Python liga SO_REUSEADDR, e no Windows isso deixa dois processos escutarem a mesma porta
    (as conexões caem em qualquer um). Aqui a porta é exclusiva: se já estiver em uso, start() falha.
    """
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        import socket
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]
