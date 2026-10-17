"""Miniaturas (foto, quadro do vídeo, capa da música, miniatura do site) e informações de mídia via ffprobe.

Tudo é gerado em segundo plano e guardado em %APPDATA%\\ScarletDM\\thumbs; a interface só lê o resultado.
"""
import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

from ..engine.task import COMPLETED
from ..util import app_data_dir, ext_of, find_ffmpeg

IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "ico", "tif", "tiff", "avif", "heic"}
VIDEO_EXTS = {"mp4", "mkv", "webm", "avi", "mov", "m4v", "wmv", "flv", "ts", "3gp", "mpg", "mpeg", "ogv", "m2ts"}
AUDIO_EXTS = {"mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "wma", "mka", "aiff", "alac"}
PLAYABLE_EXTS = VIDEO_EXTS | AUDIO_EXTS
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_playable(task):
    return task.kind != "torrent" and ext_of(task.name) in PLAYABLE_EXTS


def ffprobe_path(settings):
    ff = find_ffmpeg(settings.get("ffmpeg_path", ""))
    if ff:
        cand = os.path.join(os.path.dirname(ff), "ffprobe" + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffprobe") or ""


def fmt_duration(sec):
    sec = int(sec or 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ThumbService(QObject):
    ready = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.st = settings
        self.dir = os.path.join(app_data_dir(), "thumbs")
        os.makedirs(self.dir, exist_ok=True)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
        self._lock = threading.Lock()
        self._pending = set()
        self._failed = set()
        self._pix = {}
        self._icons = {}
        self._info = {}

    # ---------- caminhos ----------
    @staticmethod
    def _key(task):
        # o tamanho final identifica a versão do arquivo sem precisar consultar o disco a cada desenho
        return f"{task.id}-{max(0, task.total)}" if task.status == COMPLETED else f"{task.id}-p"

    def _file(self, key):
        return os.path.join(self.dir, key + ".jpg")

    def _info_file(self, key):
        return os.path.join(self.dir, key + ".json")

    # ---------- consulta (thread da interface) ----------
    def wants(self, task):
        """Vale a pena ter miniatura para esta tarefa?"""
        if task.kind == "torrent":
            return False
        if task.status == COMPLETED:
            return ext_of(task.name) in IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS
        return task.kind == "media" and bool(task.options.get("thumbnail"))

    def pixmap(self, task):
        if not self.wants(task):
            return None
        key = self._key(task)
        pm = self._pix.get(key)
        if pm is not None:
            return pm
        f = self._file(key)
        if os.path.exists(f):
            pm = QPixmap(f)
            if not pm.isNull():
                self._pix[key] = pm
                return pm
        self._request(task, key)
        return None

    def icon(self, task, size=QSize(34, 26)):
        if not self.wants(task):
            return None
        key = self._key(task)
        ic = self._icons.get(key)
        if ic is not None:
            return ic
        pm = self.pixmap(task)
        if pm is None:
            return None
        canvas = QPixmap(size.width() * 2, size.height() * 2)
        canvas.fill(Qt.GlobalColor.transparent)
        scaled = pm.scaled(canvas.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        p = QPainter(canvas)
        src = QRect((scaled.width() - canvas.width()) // 2, (scaled.height() - canvas.height()) // 2,
                    canvas.width(), canvas.height())
        p.drawPixmap(canvas.rect(), scaled, src)
        p.end()
        canvas.setDevicePixelRatio(2.0)
        ic = QIcon(canvas)
        self._icons[key] = ic
        return ic

    def info(self, task):
        if task.status != COMPLETED or ext_of(task.name) not in VIDEO_EXTS | AUDIO_EXTS:
            return None
        key = self._key(task)
        if key in self._info:
            return self._info[key]
        data = self._read_json(self._info_file(key))
        if data is not None:
            self._info[key] = data
            return data
        self._request(task, key)
        return None

    def _request(self, task, key):
        with self._lock:
            if key in self._pending or key in self._failed:
                return
            self._pending.add(key)
        snap = {"id": task.id, "path": task.path, "status": task.status,
                "thumb_url": task.options.get("thumbnail", ""), "ext": ext_of(task.name)}
        self._pool.submit(self._work, key, snap)

    # ---------- geração (thread de fundo) ----------
    def _work(self, key, s):
        ok = False
        try:
            out = self._file(key)
            if s["status"] == COMPLETED and os.path.exists(s["path"]):
                if s["ext"] in VIDEO_EXTS | AUDIO_EXTS and not os.path.exists(self._info_file(key)):
                    self._probe(key, s["path"])
                ok = os.path.exists(out) or self._make_from_file(key, s, out)
            if not ok and s["thumb_url"]:
                ok = self._make_from_url(s["thumb_url"], out)
        except Exception:  # noqa: BLE001 - miniatura é enfeite: nunca derruba nada
            ok = False
        with self._lock:
            self._pending.discard(key)
            if not ok:
                self._failed.add(key)
        self.ready.emit(s["id"])

    @staticmethod
    def _read_json(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _save_image(img, out):
        if img.isNull():
            return False
        if img.width() > 640:
            img = img.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        return img.save(out, "JPG", 88)

    def _make_from_file(self, key, s, out):
        if s["ext"] in IMAGE_EXTS:
            return self._save_image(QImage(s["path"]), out)
        ff = find_ffmpeg(self.st.get("ffmpeg_path", ""))
        if not ff:
            return False
        if s["ext"] in VIDEO_EXTS:
            dur = (self._read_json(self._info_file(key)) or {}).get("duration") or 0
            at = max(1.0, dur * 0.1) if dur else 3.0
            cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", s["path"],
                   "-frames:v", "1", "-vf", "scale=640:-2", out]
        else:   # música: capa embutida
            cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", s["path"], "-an", "-frames:v", "1",
                   "-vf", "scale=640:-2", out]
        p = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
        return p.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0

    def _make_from_url(self, url, out):
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return False
        img = QImage()
        img.loadFromData(r.content)
        return self._save_image(img, out)

    def _probe(self, key, path):
        fp = ffprobe_path(self.st)
        if not fp:
            return
        p = subprocess.run([fp, "-v", "error", "-show_entries",
                            "format=duration,bit_rate:stream=codec_type,codec_name,width,height,avg_frame_rate,"
                            "sample_rate,channels:stream_disposition=attached_pic:format_tags=title,artist,album",
                            "-of", "json", path], capture_output=True, text=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            return
        j = json.loads(p.stdout or "{}")
        fmt = j.get("format", {})
        info = {"duration": float(fmt.get("duration") or 0), "bitrate": int(fmt.get("bit_rate") or 0)}
        tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        for k in ("title", "artist", "album"):
            if tags.get(k):
                info[k] = tags[k]
        streams = j.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        for st in streams:
            if st.get("codec_type") == "video" and st.get("width") and "video" not in info:
                if (st.get("disposition") or {}).get("attached_pic") or (
                        has_audio and st.get("codec_name") in ("mjpeg", "png", "bmp", "gif", "webp")):
                    continue     # capa de música, não vídeo
                fps = st.get("avg_frame_rate", "0/1")
                try:
                    a, b = fps.split("/")
                    fps = round(int(a) / int(b)) if int(b) else 0
                except (ValueError, ZeroDivisionError):
                    fps = 0
                info["video"] = {"w": st["width"], "h": st["height"], "codec": st.get("codec_name", ""), "fps": fps}
            elif st.get("codec_type") == "audio" and "audio" not in info:
                info["audio"] = {"codec": st.get("codec_name", ""), "rate": int(st.get("sample_rate") or 0),
                                 "ch": st.get("channels") or 0}
        with open(self._info_file(key), "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        self._info[key] = info

    @staticmethod
    def describe(info):
        """Uma linha legível: '1920×1080 · 60 fps · 10:35 · H264 + AAC'."""
        if not info:
            return ""
        parts = []
        v, a = info.get("video"), info.get("audio")
        if info.get("artist"):
            parts.append(info["artist"])
        if v:
            parts.append(f"{v['w']}×{v['h']}")
            if v.get("fps"):
                parts.append(f"{v['fps']} fps")
        if info.get("duration"):
            parts.append(fmt_duration(info["duration"]))
        codecs = " + ".join(x for x in ((v or {}).get("codec", "").upper(), (a or {}).get("codec", "").upper()) if x)
        if codecs:
            parts.append(codecs)
        if a and not v and info.get("bitrate"):
            parts.append(f"{info['bitrate'] // 1000} kbps")
        return " · ".join(parts)

    def forget(self, task):
        key = self._key(task)
        self._pix.pop(key, None)
        self._icons.pop(key, None)
        with self._lock:
            self._failed.discard(key)
