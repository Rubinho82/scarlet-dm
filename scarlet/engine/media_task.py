"""Vídeos e músicas de sites (YouTube, SoundCloud, Vimeo, X, Instagram, TikTok, Twitch…).

O mecanismo (yt-dlp) roda como processo separado: funciona igual no Python e no .exe, e é atualizado
sem recompilar o app. ffmpeg e o runtime JavaScript são baixados sozinhos quando faltam (ver components.py).
Conteúdo com DRM (Spotify, Netflix, Deezer…) não é suportado.
"""
import glob
import json
import os
import subprocess
import tempfile
import time
import urllib.parse

from . import components as comp
from .components import (ytdlp_command, ytdlp_version, js_runtime_args, install_ytdlp)  # noqa: F401 (reexport)
from .task import Task, Stopped, STARTING, DOWNLOADING, PROCESSING, COMPLETED
from ..i18n import _
from ..util import sanitize_filename

CREATE_NO_WINDOW = comp.CREATE_NO_WINDOW

MEDIA_DOMAINS = (
    "youtube.com", "youtu.be", "music.youtube.com", "soundcloud.com", "vimeo.com", "dailymotion.com",
    "twitter.com", "x.com", "instagram.com", "tiktok.com", "facebook.com", "fb.watch", "twitch.tv",
    "kick.com", "reddit.com", "v.redd.it", "bilibili.com", "bandcamp.com", "mixcloud.com", "rumble.com",
    "odysee.com", "streamable.com", "pinterest.com", "linkedin.com", "tumblr.com", "vk.com", "ok.ru",
    "g1.globo.com", "ted.com", "archive.org", "audiomack.com", "threads.net",
    "bsky.app", "9gag.com", "imgur.com", "nicovideo.jp", "weibo.com", "kwai.com",
)
DRM_DOMAINS = ("spotify.com", "netflix.com", "disneyplus.com", "primevideo.com", "deezer.com", "tidal.com",
               "music.apple.com", "tv.apple.com", "max.com", "hbomax.com", "globoplay.globo.com",
               "paramountplus.com", "crunchyroll.com", "starplus.com")

# (valor, rótulo) — os rótulos são traduzidos na hora de mostrar
VIDEO_QUALITIES = [("best", "Melhor disponível"), ("2160", "4K (2160p)"), ("1440", "2K (1440p)"),
                   ("1080", "Full HD (1080p)"), ("720", "HD (720p)"), ("480", "480p"), ("360", "360p")]
FPS_CHOICES = [("", "Melhor disponível"), ("60", "60 fps (mais fluido)"), ("30", "30 fps (arquivo menor)")]
AUDIO_FORMATS = [("mp3", "MP3"), ("m4a", "M4A (AAC, sem reconverter)"), ("opus", "OPUS (sem reconverter)"),
                 ("flac", "FLAC (sem perdas)")]
AUDIO_KBPS = [("320", "320 kbps (máxima)"), ("256", "256 kbps"), ("192", "192 kbps"), ("128", "128 kbps (menor)")]
AUDIO_EXT = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "flac": "flac"}
# compatibilidade com tarefas antigas: quality = "mp3" / "m4a"
QUALITIES = VIDEO_QUALITIES + [("mp3", "Só o áudio — MP3"), ("m4a", "Só o áudio — M4A")]


def _host(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _matches(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def is_drm_url(url):
    return _matches(_host(url), DRM_DOMAINS)


def is_media_url(url):
    """Página de site de vídeo/música (não um arquivo direto)."""
    if not url.lower().startswith(("http://", "https://")):
        return False
    path = urllib.parse.urlsplit(url).path.lower()
    if os.path.splitext(path)[1] in (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".zip", ".m3u8", ".mov"):
        return False
    return _matches(_host(url), MEDIA_DOMAINS)


def update_ytdlp(log=None):
    return install_ytdlp()


def is_audio(options):
    q = str(options.get("quality", "best"))
    return q in AUDIO_EXT or q == "audio"


def audio_format(options):
    q = str(options.get("quality", "best"))
    return q if q in AUDIO_EXT else str(options.get("audio_format", "mp3"))


def common_args(settings, options):
    a = ["--no-warnings", "--no-playlist", "--encoding", "utf-8"] + js_runtime_args()
    mode = settings.get("proxy_mode", "none")
    if mode == "manual" and settings.get("proxy_url"):
        a += ["--proxy", settings["proxy_url"]]
    elif mode == "none":
        a += ["--proxy", ""]
    if not settings.get("verify_ssl", True):
        a.append("--no-check-certificates")
    if options.get("user_agent"):
        a += ["--user-agent", options["user_agent"]]
    if options.get("referer"):
        a += ["--referer", options["referer"]]
    return a


def cookies_file(url, cookie_header):
    """Converte 'a=b; c=d' (vindo da extensão) para um cookies.txt no formato Netscape."""
    if not cookie_header:
        return None
    host = _host(url)
    parts = host.split(".")
    domain = "." + ".".join(parts[-2:]) if len(parts) >= 2 else host
    fd, path = tempfile.mkstemp(prefix="sdm-cookies-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for pair in cookie_header.split(";"):
            if "=" in pair:
                k, v = pair.strip().split("=", 1)
                f.write(f"{domain}\tTRUE\t/\tTRUE\t0\t{k}\t{v}\n")
    return path


def probe_media(url, settings, options=None, timeout=90):
    """Informações do vídeo/playlist (título, duração, resoluções, se tem 60 fps, itens da playlist)."""
    cmd = ytdlp_command()
    if not cmd:
        raise RuntimeError(_("Mecanismo de vídeos ainda não instalado — ele é baixado sozinho ao começar o download"))
    options = options or {}
    args = cmd + [a for a in common_args(settings, options) if a != "--no-playlist"]
    args += ["-J", "--flat-playlist", "--yes-playlist"]
    ck = cookies_file(url, options.get("cookies"))
    if ck:
        args += ["--cookies", ck]
    args.append(url)
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
                           env=comp._env(), encoding="utf-8", errors="replace")
    finally:
        if ck:
            try:
                os.remove(ck)
            except OSError:
                pass
    if p.returncode != 0 or not p.stdout.strip():
        err = [ln for ln in p.stderr.splitlines() if "ERROR" in ln]
        raise RuntimeError((err[-1] if err else p.stderr.strip()[-300:] or _("falha ao ler o vídeo"))
                           .replace("ERROR: ", ""))
    info = json.loads(p.stdout)
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e and (e.get("url") or e.get("webpage_url"))]
        return {"playlist": True, "title": info.get("title") or "Playlist", "count": len(entries),
                "entries": [{"url": e.get("webpage_url") or e.get("url"), "title": e.get("title") or ""}
                            for e in entries]}
    vfmts = [f for f in info.get("formats") or [] if f.get("height") and f.get("vcodec") not in (None, "none")]
    heights = sorted({f["height"] for f in vfmts}, reverse=True)
    has60 = any((f.get("fps") or 0) >= 50 for f in vfmts)
    size = info.get("filesize") or info.get("filesize_approx") or 0
    return {"playlist": False, "title": info.get("title") or "", "duration": info.get("duration") or 0,
            "thumbnail": info.get("thumbnail") or "", "uploader": info.get("uploader") or info.get("channel") or "",
            "extractor": info.get("extractor_key") or info.get("extractor") or "", "heights": heights,
            "has60": has60, "size": size, "audio_only": not heights}


def format_args(options, settings):
    if is_audio(options):
        fmt = audio_format(options)
        a = ["-f", "ba/b", "-x", "--audio-format", fmt, "--embed-metadata"]
        if fmt == "mp3":
            kbps = str(options.get("audio_kbps") or settings.get("media_audio_kbps", "320"))
            a += ["--audio-quality", f"{kbps}K", "--embed-thumbnail"]
        else:
            a += ["--audio-quality", "0"]
            if fmt in ("m4a", "flac"):
                a.append("--embed-thumbnail")
        return a
    q = str(options.get("quality", "best"))
    fps = str(options.get("fps", "") or "")
    h = "" if q == "best" or not q.isdigit() else f"[height<={q}]"
    sel = f"bv*{h}+ba/b{h}/b"
    # O fps é preferência dentro da resolução escolhida (não derruba a resolução):
    # "+fps" = prefere o menor (30), "fps" = prefere o maior (60).
    sort = [f"res:{q}" if q.isdigit() else "res", "+fps" if fps == "30" else "fps"]
    if settings.get("media_compat"):
        sort += ["vcodec:h264", "acodec:m4a"]
    container = settings.get("media_container", "mp4")
    a = ["-f", sel, "-S", ",".join(sort), "--merge-output-format", container, "--embed-metadata"]
    if settings.get("media_subs"):
        a += ["--write-subs", "--sub-langs", "pt.*,en.*", "--embed-subs"]
    return a


def quality_label(options):
    """Texto curto para a interface: '1080p · 60 fps', 'MP3 320 kbps'…"""
    if is_audio(options):
        fmt = audio_format(options)
        if fmt == "mp3":
            return f"MP3 {options.get('audio_kbps') or '320'} kbps"
        return fmt.upper()
    q = str(options.get("quality", "best"))
    fps = str(options.get("fps", "") or "")
    base = _("melhor qualidade") if q == "best" else f"{q}p"
    return base + (f" · {fps} fps" if fps else "")


class MediaTask(Task):
    kind = "media"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._proc = None
        self._base_done = 0
        self._cur_done = 0
        self._cur_total = 0
        self._last_file = ""
        self.stage = ""

    @property
    def quality(self):
        return str(self.options.get("quality", "best"))

    def _ext(self):
        return AUDIO_EXT[audio_format(self.options)] if is_audio(self.options) else (
            self.manager.settings.get("media_container", "mp4") if self.manager else "mp4")

    @property
    def name(self):
        if self.filename:
            return self.filename
        t = (self.options.get("title") or "").strip()
        if t:
            return sanitize_filename(t) + "." + self._ext()
        return self.url

    @property
    def category(self):
        return "audio" if is_audio(self.options) else "video"

    @property
    def done(self):
        return self._base_done + self._cur_done

    @property
    def connections_active(self):
        return 1 if self._proc is not None else 0

    def progress(self):
        if self.status == COMPLETED:
            return 1.0
        tot = self._base_done + self._cur_total
        if self._cur_total > 0 and tot > 0:
            return min(1.0, self.done / tot)
        return None

    def eta(self):
        if self.speed <= 0 or self._cur_total <= 0:
            return None
        return max(0, self._cur_total - self._cur_done) / self.speed

    def is_retryable(self, e):
        text = str(e).lower()
        if any(k in text for k in ("403", "private", "unavailable", "not available", "drm", "sign in")):
            return False
        return super().is_retryable(e)

    def _stem(self):
        return os.path.splitext(self.name)[0] if self.filename or self.options.get("title") else "%(title).150B"

    # ---------- componentes ----------
    def _install(self, label, fn):
        self.status = PROCESSING
        self.stage = label
        self.logmsg(label)

        def prog(done, total):
            if self._stop.is_set():
                raise Stopped()
            self.stage = f"{label} {done * 100 // max(1, total)}%"
        try:
            fn(prog)
        except Stopped:
            raise
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(_("Não foi possível baixar um componente necessário ({erro}). "
                                 "Verifique a internet e tente de novo.").format(erro=e)) from e
        self.stage = ""

    def _ensure_components(self, st):
        if not ytdlp_command():
            self._install(_("Preparando o mecanismo de vídeos…"), comp.install_ytdlp)
            st["ytdlp_last_update"] = time.time()
        if not comp.ffmpeg_path(st.get("ffmpeg_path", "")):
            self._install(_("Baixando o conversor de vídeo (uma vez só)…"), comp.install_ffmpeg)
        if comp.needs_js(self.url) and not comp.js_runtime()[0]:
            self._install(_("Baixando o componente do YouTube (uma vez só)…"), comp.install_deno)

    # ---------- execução ----------
    def run(self):
        st = self.manager.settings
        self.status = STARTING
        self._ensure_components(st)
        cmd = ytdlp_command()
        if not cmd:
            raise RuntimeError(_("Mecanismo de vídeos indisponível"))
        os.makedirs(self.save_dir, exist_ok=True)
        self.status = STARTING
        self._base_done = self._cur_done = self._cur_total = 0
        self._last_file = ""
        if not self.filename and not self.options.get("title"):
            try:
                info = probe_media(self.url, st, self.options)
                if not info.get("playlist") and info.get("title"):
                    self.options["title"] = info["title"]
                    if info.get("thumbnail"):
                        self.options.setdefault("thumbnail", info["thumbnail"])
                    self.dirty = True
            except Exception as e:  # noqa: BLE001 - sem título o mecanismo escolhe o nome
                self.logmsg(_("Não consegui ler o título antes: {erro}").format(erro=e))
            if self._stop.is_set():
                raise Stopped()
        if not self.filename and self.options.get("title"):
            # reserva o nome (título (1).mp4…) para não confundir com outro download do mesmo vídeo
            want = sanitize_filename(self.options["title"]) + "." + self._ext()
            self.filename = self.manager.reserve_filename(self, self.save_dir, want)
            self.dirty = True
        stem = self._stem()
        if not stem.startswith("%("):
            stem = sanitize_filename(stem)
        out = os.path.join(self.save_dir, stem + ".%(ext)s")
        n = max(1, min(16, int(self.options.get("connections") or st.get("connections", 8))))
        args = cmd + common_args(st, self.options) + format_args(self.options, st) + [
            "-o", out, "--windows-filenames", "--no-mtime",
        ] + (["--force-overwrites"] if st.get("on_exists") == "overwrite" else []) + [ "-N", str(n), "--http-chunk-size", "10M",
            "--continue", "--retries", str(st.get("retries", 10)), "--fragment-retries", str(st.get("retries", 10)),
            "--no-simulate", "--progress", "--newline",
            "--progress-template", "download:SDMPROG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                                   "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.filename)s",
            "--progress-template", "postprocess:SDMPOST|%(progress.postprocessor)s|%(progress.status)s",
            "--print", "after_move:SDMFILE|%(filepath)s",
        ]
        ff = comp.ffmpeg_path(st.get("ffmpeg_path", ""))
        if ff:
            args += ["--ffmpeg-location", ff]
        if st.get("limit_enabled") and st.get("speed_limit"):
            args += ["--limit-rate", str(int(st["speed_limit"]))]
        ck = cookies_file(self.url, self.options.get("cookies"))
        if ck:
            args += ["--cookies", ck]
        args.append(self.url)
        self.logmsg(_("Vídeo: {q}, {n} conexões por fragmento").format(q=quality_label(self.options), n=n))
        try:
            for attempt in range(3):
                final, rc, tail = self._run_once(args)
                if self._stop.is_set():
                    raise Stopped()
                transient = any(k in " ".join(tail) for k in ("HTTP Error 403", "HTTP Error 5", "timed out",
                                                                "Connection reset"))
                if (rc == 0 and final) or not transient or attempt == 2:
                    break
                self.logmsg(_("O site recusou a conexão; tentando de novo ({n}/2)…").format(n=attempt + 1))
                if self._halt.wait(3 + attempt * 4):
                    raise Stopped()
        finally:
            if ck:
                try:
                    os.remove(ck)
                except OSError:
                    pass
        self._finish(final, rc, tail)

    def _run_once(self, args):
        final = None
        tail = []
        rc = -1
        try:
            self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                          encoding="utf-8", errors="replace", bufsize=1, env=comp._env(),
                                          creationflags=CREATE_NO_WINDOW)
            for line in self._proc.stdout:
                line = line.rstrip("\r\n")
                if self._stop.is_set():
                    break
                if line.startswith("SDMPROG|"):
                    self._on_progress(line.split("|"))
                elif line.startswith("SDMPOST|"):
                    parts = line.split("|")
                    self.status = PROCESSING
                    self.stage = {"Merger": _("Juntando áudio e vídeo"), "ExtractAudio": _("Convertendo o áudio"),
                                  "EmbedThumbnail": _("Colocando a capa"), "FFmpegMetadata": _("Gravando informações"),
                                  "EmbedSubtitle": _("Embutindo legendas")}.get(parts[1], _("Finalizando"))
                elif line.startswith("SDMFILE|"):
                    final = line.split("|", 1)[1].strip()
                elif line.strip():
                    tail.append(line)
                    tail = tail[-12:]
                    if "ERROR" in line:
                        self.logmsg(line.replace("yt-dlp", "").replace("ERROR: ", ""))
            rc = self._proc.wait()
        finally:
            self._proc = None
        return final, rc, tail

    def _finish(self, final, rc, tail):
        if rc != 0 or not final:
            errs = [ln.replace("ERROR: ", "") for ln in tail if "ERROR" in ln]
            msg = errs[-1] if errs else (tail[-1] if tail else _("o download terminou com erro ({rc})").format(rc=rc))
            if "403" in msg or "Sign in" in msg or "confirm you" in msg:
                msg += " — " + _("tente Preferências › Vídeos de sites › Atualizar")
            raise RuntimeError(msg.replace("yt-dlp", "")[:400])
        self.filename = os.path.basename(final)
        self.save_dir = os.path.dirname(final) or self.save_dir
        try:
            self.total = os.path.getsize(final)
        except OSError:
            self.total = self.done
        self._base_done, self._cur_done, self._cur_total = self.total, 0, 0
        self.stage = ""
        self.logmsg(_("Salvo em {caminho}").format(caminho=final))
        self.status = COMPLETED
        self.finished = time.time()
        self.dirty = True

    def _on_progress(self, p):
        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0
        done, tot, est = num(p[1]), num(p[2]), num(p[3])
        fn = p[5] if len(p) > 5 else ""
        if fn and fn != self._last_file:
            if self._last_file:
                self._base_done += self._cur_total or self._cur_done
            self._last_file = fn
        self._cur_done = int(done)
        self._cur_total = int(tot or est or 0)
        self.status = DOWNLOADING
        self.stage = ""

    def on_stop(self):
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                               creationflags=CREATE_NO_WINDOW, timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def delete_files(self, include_completed=True):
        stem = self._stem()
        if stem.startswith("%("):
            return
        base = os.path.join(self.save_dir, glob.escape(stem))
        for p in glob.glob(base + ".*"):
            is_final = os.path.normcase(p) == os.path.normcase(self.path)
            if is_final and not (include_completed and self.status == COMPLETED):
                continue
            leftovers = (".part", ".ytdl", ".temp")
            if is_final or p.endswith(leftovers) or ".part-Frag" in p or ".f" in os.path.basename(p)[len(stem):]:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def reset(self):
        self.delete_files(include_completed=False)
        super().reset()
        self._base_done = self._cur_done = self._cur_total = 0

    def to_dict(self):
        d = super().to_dict()
        d["done_cache"] = self.done if self.status == COMPLETED else 0
        return d

    def load_dict(self, d):
        super().load_dict(d)
        if self.status == COMPLETED:
            self._base_done = d.get("done_cache", self.total)
