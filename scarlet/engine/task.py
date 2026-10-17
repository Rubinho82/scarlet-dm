"""Classe base das tarefas de download (HTTP, HLS e torrent)."""
import os
import threading
import time
import traceback
import uuid
from collections import deque

from ..util import category_for, filename_from_url

QUEUED = "queued"
STARTING = "starting"
DOWNLOADING = "downloading"
PAUSED = "paused"
COMPLETED = "completed"
ERROR = "error"
PROCESSING = "processing"
SEEDING = "seeding"

STATUS_LABELS = {
    QUEUED: "Na fila",
    STARTING: "Conectando…",
    DOWNLOADING: "Baixando",
    PAUSED: "Pausado",
    COMPLETED: "Concluído",
    ERROR: "Erro",
    PROCESSING: "Processando…",
    SEEDING: "Semeando",
}

ACTIVE_STATES = {STARTING, DOWNLOADING, PROCESSING}


class Stopped(Exception):
    pass


class Task:
    kind = "base"
    reports_own_speed = False

    def __init__(self, url="", save_dir="", filename=None, options=None, id=None):
        self.id = id or uuid.uuid4().hex[:12]
        self.url = url
        self.save_dir = save_dir
        self.filename = filename
        self.filename_fixed = bool(filename)
        self.options = dict(options or {})
        self.status = QUEUED
        self.error = ""
        self.added = time.time()
        self.finished = None
        self.total = -1
        self.speed = 0.0
        self.up_speed = 0.0
        self.speed_history = deque(maxlen=120)
        self.log = deque(maxlen=500)
        self.missing = False
        self.retryable = False
        self.error_at = 0.0
        self.auto_retries = 0
        self.remove_at = 0.0
        self.manager = None
        self.lock = threading.RLock()
        self.dirty = True
        self._samples = deque()
        self._thread = None
        self._stop = threading.Event()
        self._halt = threading.Event()

    # ---------- propriedades ----------
    @property
    def name(self):
        return self.filename or filename_from_url(self.url)

    @property
    def path(self):
        return os.path.join(self.save_dir, self.name)

    @property
    def done(self):
        return 0

    @property
    def category(self):
        return category_for(self.name)

    def progress(self):
        if self.status == COMPLETED:
            return 1.0
        if self.total > 0:
            return min(1.0, self.done / self.total)
        return None

    def eta(self):
        if self.speed <= 0 or self.total <= 0:
            return None
        return max(0, self.total - self.done) / self.speed

    @property
    def connections_active(self):
        return 0

    # ---------- controle ----------
    def logmsg(self, msg):
        self.log.append((time.time(), str(msg)))

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running() or self.status == COMPLETED:
            return
        self._stop.clear()
        self._halt.clear()
        self.error = ""
        self.status = STARTING
        self.dirty = True
        self._samples.clear()
        self._thread = threading.Thread(target=self._run_wrapper, name=f"task-{self.id}", daemon=True)
        self._thread.start()

    def _run_wrapper(self):
        try:
            self.run()
        except Stopped:
            pass
        except Exception as e:  # noqa: BLE001 - qualquer falha vira estado de erro visível
            if not self._stop.is_set():
                self.status = ERROR
                self.error = self.describe_error(e)
                self.error_at = time.time()
                try:
                    self.retryable = bool(self.is_retryable(e))
                except Exception:
                    self.retryable = False
                self.logmsg(f"Falhou: {self.error}")
                self.logmsg(traceback.format_exc(limit=3))
        finally:
            if self._stop.is_set() and self.status not in (COMPLETED, ERROR):
                self.status = PAUSED
            self.speed = 0.0
            self.dirty = True

    def describe_error(self, e):
        return str(e) or e.__class__.__name__

    def is_retryable(self, e):
        """Erro passageiro (rede caiu, servidor ocupado)? Usado pela nova tentativa automática."""
        text = str(e).lower()
        return isinstance(e, (ConnectionError, TimeoutError)) or any(
            k in text for k in ("timed out", "timeout", "connection", "conex", "reset", "temporar",
                                "incompleteread", "interrompido", "parou de responder"))

    def run(self):
        raise NotImplementedError

    def pause(self):
        self._stop.set()
        self._halt.set()
        self.on_stop()
        if not self.is_running() and self.status in (QUEUED, STARTING, DOWNLOADING, PROCESSING):
            self.status = PAUSED
        self.dirty = True

    def on_stop(self):
        pass

    def wait(self, timeout=None):
        t = self._thread
        if t is not None:
            t.join(timeout)

    def stopped(self):
        return self._halt.is_set()

    def reset(self):
        """Volta ao estado inicial (usado por 'Reiniciar')."""
        self.total = -1
        self.error = ""
        self.finished = None
        if not self.filename_fixed:
            self.filename = None

    def delete_files(self, include_completed=True):
        pass

    def update_speed(self, now):
        if self.reports_own_speed:
            if self.speed or (self.speed_history and self.speed_history[-1]):
                self.speed_history.append(self.speed)
            return
        if self.status not in ACTIVE_STATES:
            self._samples.clear()
            self.speed = 0.0
            if self.speed_history and self.speed_history[-1] != 0.0:
                self.speed_history.append(0.0)      # fecha o gráfico em zero e para de gastar
            return
        d = self.done
        self._samples.append((now, d))
        while len(self._samples) > 2 and now - self._samples[0][0] > 3.0:
            self._samples.popleft()
        t0, d0 = self._samples[0]
        dt = now - t0
        self.speed = max(0.0, (d - d0) / dt) if dt > 0.2 else self.speed
        self.speed_history.append(self.speed)

    # ---------- persistência ----------
    def to_dict(self):
        return {
            "kind": self.kind,
            "id": self.id,
            "url": self.url,
            "save_dir": self.save_dir,
            "filename": self.filename,
            "filename_fixed": self.filename_fixed,
            "options": self.options,
            "status": self.status,
            "error": self.error,
            "added": self.added,
            "finished": self.finished,
            "total": self.total,
        }

    def load_dict(self, d):
        self.filename_fixed = d.get("filename_fixed", bool(self.filename))
        self.status = d.get("status", PAUSED)
        self.error = d.get("error", "")
        self.added = d.get("added", time.time())
        self.finished = d.get("finished")
        self.total = d.get("total", -1)
        if self.status in ACTIVE_STATES:
            self.status = QUEUED
        self.dirty = False
