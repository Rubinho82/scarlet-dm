"""Converter um arquivo já baixado (ffmpeg): MP3, MP4 compatível ou vídeo comprimido.

Aparece na lista como um download: barra de progresso, pausar (recomeça do zero ao continuar), erro visível e o
arquivo novo ao lado do original quando termina. O ffmpeg é baixado na primeira vez, se não houver.
"""
import os
import subprocess
import time

from ..i18n import _
from . import components as comp
from .task import COMPLETED, PROCESSING, STARTING, Stopped, Task

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# preset -> (extensão, rótulo, argumentos do ffmpeg entre a entrada e a saída)
PRESETS = {
    "mp3": ("mp3", "MP3 (320 kbps)",
            ["-vn", "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k", "-map_metadata", "0",
             "-id3v2_version", "3"]),
    "mp4": ("mp4", "MP4 (H.264/AAC)",
            ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]),
    "compress": ("mp4", "Vídeo comprimido",
                 ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "faster", "-crf", "28",
                  "-vf", "scale='min(1280,iw)':-2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                  "-movflags", "+faststart"]),
}
SUFFIX = {"mp3": "", "mp4": " (convertido)", "compress": " (comprimido)"}
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv", ".m4v", ".ts", ".3gp", ".mpg", ".mpeg")
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".flac", ".wav", ".wma")


def presets_for(path):
    """Quais conversões fazem sentido para este arquivo."""
    low = path.lower()
    if low.endswith(VIDEO_EXT):
        return ["mp3", "mp4", "compress"]
    if low.endswith(AUDIO_EXT) and not low.endswith(".mp3"):
        return ["mp3"]
    return []


def output_name(source, preset):
    """Nome do arquivo convertido, na mesma pasta, sem sobrescrever nada."""
    folder = os.path.dirname(source)
    stem = os.path.splitext(os.path.basename(source))[0]
    ext = PRESETS[preset][0]
    base = stem + SUFFIX[preset]
    name, n = f"{base}.{ext}", 1
    while os.path.exists(os.path.join(folder, name)) or os.path.exists(os.path.join(folder, name + ".sdmconv")):
        name = f"{base} ({n}).{ext}"
        n += 1
    return name


class ConvertTask(Task):
    kind = "convert"
    reports_own_speed = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._proc = None
        self._done_ms = 0
        self.stage = ""

    @property
    def source(self):
        return self.options.get("source", "")

    @property
    def preset(self):
        return self.options.get("preset", "mp3")

    @property
    def category(self):
        return "audio" if self.preset == "mp3" else "video"

    @property
    def done(self):
        return self._done_ms

    def progress(self):
        if self.status == COMPLETED:
            return 1.0
        return min(1.0, self._done_ms / self.total) if self.total > 0 else None

    def eta(self):
        started = self.options.get("_started")
        p = self.progress()
        if not started or not p or p <= 0.01:
            return None
        return (time.time() - started) * (1 - p) / p

    @property
    def connections_active(self):
        return 1 if self._proc is not None else 0

    def is_retryable(self, e):
        return False

    def on_stop(self):
        p = self._proc
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass

    def _ffmpeg(self, st):
        ff = comp.ffmpeg_path(st.get("ffmpeg_path", ""))
        if ff:
            return ff
        self.status = PROCESSING
        label = _("Baixando o conversor de vídeo (uma vez só)…")
        self.stage = label

        def prog(done, total):
            if self._stop.is_set():
                raise Stopped()
            self.stage = f"{label} {done * 100 // max(1, total)}%"
        comp.install_ffmpeg(prog)
        return comp.ffmpeg_path(st.get("ffmpeg_path", ""))

    def _duration_ms(self):
        probe = comp.ffprobe_path(self.manager.settings.get("ffmpeg_path", ""))
        if not probe:
            return -1
        try:
            p = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                self.source], capture_output=True, text=True, timeout=60,
                               creationflags=CREATE_NO_WINDOW)
            return int(float(p.stdout.strip()) * 1000)
        except (OSError, ValueError, subprocess.SubprocessError):
            return -1

    def run(self):
        st = self.manager.settings
        self.status = STARTING
        if not os.path.isfile(self.source):
            raise RuntimeError(_("O arquivo original não existe mais: {p}").format(p=self.source))
        ff = self._ffmpeg(st)
        if not ff:
            raise RuntimeError(_("Conversor de vídeo indisponível"))
        self.total = self._duration_ms()
        self._done_ms = 0
        self.options["_started"] = time.time()
        ext, label, args = PRESETS[self.preset]
        out = self.path
        tmp = out + ".sdmconv"
        cmd = [ff, "-hide_banner", "-nostdin", "-y", "-i", self.source] + args + \
              ["-f", "mp3" if ext == "mp3" else "mp4", "-progress", "pipe:1", "-nostats", "-loglevel", "error", tmp]
        self.status = PROCESSING
        self.stage = _("Convertendo para {f}").format(f=_(label))
        self.logmsg(f"ffmpeg: {self.preset} -> {out}")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        try:
            for line in self._proc.stdout:
                if self._stop.is_set():
                    raise Stopped()
                key, _sep, val = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and val.isdigit():
                    self._done_ms = int(val) // 1000          # o ffmpeg chama de "ms", mas é microssegundo
                    if self.total > 0:
                        self.stage = _("Convertendo para {f}").format(f=_(label)) + \
                            f" · {min(100, self._done_ms * 100 // self.total)}%"
                    self.dirty = True
            rc = self._proc.wait()
            err = (self._proc.stderr.read() or "").strip().splitlines()
        finally:
            self._proc = None
        if self._stop.is_set():
            self._cleanup(tmp)
            raise Stopped()
        if rc != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            self._cleanup(tmp)
            raise RuntimeError(_("A conversão falhou: {e}").format(e=(err[-1] if err else rc)))
        os.replace(tmp, out)
        self._done_ms = max(self._done_ms, self.total)
        self.stage = ""
        self.finished = time.time()
        self.status = COMPLETED
        self.dirty = True

    @staticmethod
    def _cleanup(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass

    def delete_files(self, include_completed=True):
        self._cleanup(self.path + ".sdmconv")
        if include_completed and self.status == COMPLETED:
            try:
                os.remove(self.path)
            except OSError:
                pass
