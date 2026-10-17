"""Gerenciador: lista de tarefas, fila, persistência, agendador e eventos para a interface."""
import collections
import json
import os
import shutil
import threading
import time
import urllib.parse

import glob
import subprocess

from .task import (QUEUED, PAUSED, COMPLETED, ERROR, ACTIVE_STATES, SEEDING)
from .http_task import HttpTask, PART_EXT
from .hls_task import HlsTask
from .media_task import MediaTask, is_media_url, is_drm_url
from .torrent import TorrentTask, TorrentEngine, lt
from .ratelimit import RateLimiter
from ..i18n import _
from ..util import (app_data_dir, unique_path, category_for, CATEGORY_LABELS, sanitize_filename,
                    filename_from_url, mark_of_the_web)

KINDS = {"http": HttpTask, "hls": HlsTask, "torrent": TorrentTask, "media": MediaTask}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_defender():
    """Antivírus padrão: MpCmdRun.exe do Windows Defender; no Linux/macOS, o ClamAV se estiver instalado."""
    if os.name != "nt":
        return shutil.which("clamdscan") or shutil.which("clamscan") or ""
    cands = sorted(glob.glob(os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                          r"Microsoft\Windows Defender\Platform\*\MpCmdRun.exe")))
    if cands:
        return cands[-1]
    p = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Windows Defender\MpCmdRun.exe")
    return p if os.path.exists(p) else ""


class Manager:
    def __init__(self, settings, db_path=None):
        self.settings = settings
        self.tasks = []
        self.lock = threading.RLock()
        self.limiter = RateLimiter()
        self.torrents = TorrentEngine(self)
        self.events = collections.deque()
        self.db_path = db_path or os.path.join(app_data_dir(), "downloads.json")
        self._last_save = 0.0
        self._last_missing = 0.0
        self._prev = {}
        self._structure_dirty = False
        self._sched_last = ""
        self._last_watch = 0.0
        self._last_backup = 0.0
        self.apply_limits()

    # ---------- configuração ----------
    def apply_limits(self):
        st = self.settings
        self.limiter.set_rate(st.get("speed_limit", 0) if st.get("limit_enabled") else 0)
        self.torrents.apply_limits()

    # ---------- persistência ----------
    def load(self):
        try:
            with open(self.db_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            try:
                shutil.copy2(self.db_path, self.db_path + ".corrompido")
            except OSError:
                pass
            return
        for d in data.get("tasks", []):
            cls = KINDS.get(d.get("kind"))
            if cls is None:
                continue
            t = cls(d.get("url", ""), d.get("save_dir", ""), d.get("filename"), d.get("options"), id=d.get("id"))
            t.load_dict(d)
            t.manager = self
            self.tasks.append(t)
            self._prev[t.id] = t.status

    def save(self, force=False):
        with self.lock:
            tasks = list(self.tasks)
        busy = any(t.status in ACTIVE_STATES for t in tasks)
        if not (force or busy or self._structure_dirty or any(t.dirty for t in tasks)):
            return
        data = {"version": 1, "tasks": [t.to_dict() for t in tasks]}
        tmp = self.db_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.db_path)
        for t in tasks:
            t.dirty = False
        self._structure_dirty = False
        self._last_save = time.time()
        self._backup()

    def _backup(self):
        hours = float(self.settings.get("backup_hours", 0) or 0)
        if hours <= 0 or time.time() - self._last_backup < 60:
            return
        d = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(d, exist_ok=True)
        existing = sorted(glob.glob(os.path.join(d, "downloads-*.json")))
        newest = os.path.getmtime(existing[-1]) if existing else 0
        self._last_backup = time.time()
        if time.time() - newest < hours * 3600:
            return
        shutil.copy2(self.db_path, os.path.join(d, time.strftime("downloads-%Y%m%d-%H%M%S.json")))
        for old in existing[:-9]:
            try:
                os.remove(old)
            except OSError:
                pass

    # ---------- nomes e pastas ----------
    def dir_for(self, name, kind):
        base = self.settings["download_dir"]
        if self.settings.get("category_subfolders"):
            cat = "torrent" if kind == "torrent" else category_for(name)
            if cat != "other":
                return os.path.join(base, _(CATEGORY_LABELS[cat]))
        return base

    def _taken(self, task, save_dir):
        out = set()
        with self.lock:
            for t in self.tasks:
                if t is not task and t.filename and os.path.normcase(t.save_dir) == os.path.normcase(save_dir):
                    out.add(os.path.join(save_dir, t.filename))
        return out

    def _overwrite(self):
        return self.settings.get("on_exists") == "overwrite"

    def reserve_filename(self, task, save_dir, name):
        taken = self._taken(task, save_dir)
        p = os.path.join(save_dir, name)
        if self._overwrite():
            # sobrescrever arquivos do disco, mas nunca o de outro download da lista
            norm = {os.path.normcase(x) for x in taken}
            stem, ext = os.path.splitext(p)
            i = 1
            while os.path.normcase(p) in norm:
                p = f"{stem} ({i}){ext}"
                i += 1
            return os.path.basename(p)
        while True:
            p = unique_path(p, taken)
            # Um .sdm de outro download incompleto também ocupa o nome.
            if os.path.exists(p + PART_EXT) and task.kind == "http" and not task.segments:
                owner = any(t is not task and t.path == p for t in self.tasks)
                if owner:
                    taken.add(p)
                    continue
            return os.path.basename(p)

    def final_path(self, task):
        p = task.path
        taken = self._taken(task, task.save_dir)
        in_list = os.path.normcase(p) in {os.path.normcase(x) for x in taken}
        if self._overwrite() and not in_list:
            return p
        if os.path.exists(p) or in_list:
            p = unique_path(p, taken)
        return p

    # ---------- conexões ----------
    def conn_budget(self, task):
        """Quantas conexões novas esta tarefa ainda pode abrir (limite por servidor e total)."""
        st = self.settings
        total_cap = int(st.get("max_total_conns", 96) or 96)
        host_cap = int(st.get("max_per_server", 16) or 16)
        host = task.host
        used_total = used_host = 0
        for t in list(self.tasks):
            if t.kind != "http":
                continue
            n = t.active_nolock
            used_total += n
            if t.host == host:
                used_host += n
        return max(0, min(total_cap - used_total, host_cap - used_host))

    # ---------- adicionar ----------
    def find_duplicate(self, url):
        with self.lock:
            return next((t for t in self.tasks if t.url == url), None)

    def add(self, url, save_dir=None, filename=None, options=None, start=True):
        url = url.strip()
        options = dict(options or {})
        low = url.lower()
        if os.path.isfile(url) and low.endswith(".torrent"):
            return self.add_torrent_file(url, save_dir, start)
        kind = options.pop("kind", "")
        if low.startswith("magnet:?"):
            cls = TorrentTask
        elif kind == "media" or (kind not in ("http", "hls") and is_media_url(url)):
            cls = MediaTask
            st = self.settings
            options.setdefault("quality", st.get("media_quality", "best"))
            options.setdefault("fps", st.get("media_fps", ""))
            options.setdefault("audio_format", st.get("media_audio_format", "mp3"))
            options.setdefault("audio_kbps", str(st.get("media_audio_kbps", "320")))
        elif urllib.parse.urlsplit(url).path.lower().endswith(".m3u8") or kind == "hls":
            cls = HlsTask
        else:
            cls = HttpTask
        name = sanitize_filename(filename) if filename else None
        if cls is MediaTask:
            save_dir = save_dir or self.dir_for("x." + ("mp3" if str(options.get("quality")) in ("mp3", "m4a", "audio")
                                                        else "mp4"), "http")
        else:
            save_dir = save_dir or self.dir_for(name or filename_from_url(url), cls.kind)
        t = cls(url, save_dir, name, options)
        t.manager = self
        if cls is HlsTask:
            t.filename = self.reserve_filename(t, save_dir, t.filename)
        if is_drm_url(url):
            t.status = ERROR
            t.error = _("Conteúdo protegido por DRM (Spotify, Netflix, Deezer…): não é possível baixar. "
                       "Músicas e vídeos de YouTube, SoundCloud, Vimeo etc. funcionam.")
        elif cls is TorrentTask and not lt:
            t.status, t.error = ERROR, _("Suporte a torrent indisponível nesta instalação")
        else:
            t.status = QUEUED if start else PAUSED
        with self.lock:
            self.tasks.append(t)
        self._prev[t.id] = t.status
        self._structure_dirty = True
        t.logmsg("Adicionado")
        return t

    def add_torrent_file(self, path, save_dir=None, start=True):
        t = TorrentTask("", "", None, {"source_path": os.path.abspath(path)})
        dest = os.path.join(self.torrents.dir, t.id + ".torrent")
        shutil.copy2(path, dest)
        t.torrent_file = dest
        if bool(lt):
            try:
                t._name = lt.torrent_info(dest).name()
            except Exception as e:  # noqa: BLE001
                os.remove(dest)
                raise RuntimeError(_("Arquivo .torrent inválido: {erro}").format(erro=e)) from e
        t.save_dir = save_dir or self.dir_for(t.name, "torrent")
        t.manager = self
        if not lt:
            t.status, t.error = ERROR, _("Suporte a torrent indisponível nesta instalação")
        else:
            t.status = QUEUED if start else PAUSED
        with self.lock:
            self.tasks.append(t)
        self._prev[t.id] = t.status
        self._structure_dirty = True
        return t

    # ---------- controle ----------
    def active_count(self):
        return sum(1 for t in self.tasks if t.status in ACTIVE_STATES)

    def start(self, task):
        """Início pedido pelo usuário: começa na hora, sem esperar a fila."""
        if task.status == COMPLETED and task.kind != "torrent":
            return
        task.start()

    def queue(self, task):
        if task.status in (PAUSED, ERROR):
            task.status = QUEUED
            task.error = ""
            task.dirty = True

    def pause(self, task):
        task.pause()

    def pause_all(self):
        for t in list(self.tasks):
            if t.status in ACTIVE_STATES or t.status in (QUEUED, SEEDING):
                t.pause()

    def resume_all(self):
        for t in list(self.tasks):
            self.queue(t)

    def remove(self, tasks, delete_files=False):
        tasks = list(tasks)
        with self.lock:
            for t in tasks:
                if t in self.tasks:
                    self.tasks.remove(t)
                self._prev.pop(t.id, None)
        self._structure_dirty = True

        def job():
            for t in tasks:
                if t.kind == "torrent":
                    t.detach(delete_files)
                    if t.torrent_file and os.path.exists(t.torrent_file):
                        os.remove(t.torrent_file)
                    continue
                t.pause()
                t.wait(15)
                t.delete_files(include_completed=delete_files)
        threading.Thread(target=job, daemon=True).start()

    def restart(self, task):
        def job():
            task.pause()
            task.wait(15)
            if task.kind == "http":
                task.delete_files(include_completed=False)
            task.reset()
            task.status = QUEUED
            task.dirty = True
            task.logmsg("Reiniciado do zero")
        threading.Thread(target=job, daemon=True).start()

    def change_url(self, task, url):
        task.url = url.strip()
        task.logmsg(f"Link alterado para {task.url}")
        if task.status == ERROR:
            task.status = QUEUED
            task.error = ""
        task.dirty = True

    def _convert_to_hls(self, old):
        new = HlsTask(old.url, old.save_dir, None, old.options, id=old.id)
        new.added = old.added
        new.manager = self
        new.filename = self.reserve_filename(new, new.save_dir, new.filename)
        new.log.extend(old.log)
        old.delete_files(include_completed=False)
        with self.lock:
            i = self.tasks.index(old)
            self.tasks[i] = new
        self._structure_dirty = True
        new.start()

    # ---------- laço principal (chamado pela interface a cada ~0,5 s) ----------
    def tick(self):
        now = time.monotonic()
        try:
            self.torrents.pump()
        except Exception:
            pass
        with self.lock:
            tasks = list(self.tasks)
        for t in tasks:
            if t.kind == "torrent":
                try:
                    t.refresh()
                except Exception as e:  # noqa: BLE001
                    t.logmsg(f"Erro ao ler status: {e}")
            t.update_speed(now)
            if getattr(t, "convert_to", None) == "hls" and not t.is_running():
                t.convert_to = None
                self._convert_to_hls(t)
        changed = False
        for t in tasks:
            prev = self._prev.get(t.id)
            if prev != t.status:
                if t.status == COMPLETED and prev is not None:
                    self._on_completed(t)
                elif t.status == ERROR and prev is not None:
                    self.events.append(("error", t))
                self._prev[t.id] = t.status
                changed = changed or t.status in (COMPLETED, ERROR, PAUSED)
        if changed:
            self._last_save = 0   # grava já: concluído não pode "voltar" a baixar se o app cair
        self._schedule()
        active = self.active_count()
        limit = max(1, int(self.settings.get("max_active", 3)))
        for t in tasks:
            if active >= limit:
                break
            if t.status == QUEUED and not t.is_running():
                t.start()
                active += 1
        now_wall = time.time()
        st = self.settings
        if now_wall - self._last_missing > 5:
            self._last_missing = now_wall
            gone = []
            for t in tasks:
                t.missing = t.status == COMPLETED and t.kind != "torrent" and not os.path.exists(t.path)
                if t.missing and st.get("autoremove_missing"):
                    gone.append(t)
            if gone:
                self.remove(gone, delete_files=False)
        # nova tentativa automática de downloads que falharam por erro passageiro (rede, servidor ocupado)
        if st.get("auto_retry", True):
            for t in tasks:
                if (t.status == ERROR and t.retryable and t.auto_retries < 5
                        and now_wall - t.error_at > 30 * (t.auto_retries + 1)):
                    t.auto_retries += 1
                    t.logmsg(f"Nova tentativa automática ({t.auto_retries}/5)")
                    self.queue(t)
        # remover concluídos da lista (opção do FDM)
        for t in tasks:
            if t.remove_at and now_wall >= t.remove_at:
                t.remove_at = 0
                if t.status == COMPLETED:
                    self.remove([t], delete_files=False)
        if now_wall - self._last_watch > 5:
            self._last_watch = now_wall
            self._watch_folder()
        if time.time() - self._last_save > 3:
            try:
                self.save()
            except OSError:
                pass

    # ---------- depois de concluir ----------
    def _on_completed(self, t):
        self.events.append(("completed", t))
        st = self.settings
        if st.get("autoremove_completed"):
            t.remove_at = time.time() + 8
        if t.kind == "torrent" and st.get("torrent_delete_source"):
            src = t.options.get("source_path")
            if src and os.path.isfile(src):
                try:
                    os.remove(src)
                    t.logmsg(f"Arquivo .torrent original apagado: {src}")
                except OSError:
                    pass
        threading.Thread(target=self._post_process, args=(t,), daemon=True).start()

    def _post_process(self, t):
        st = self.settings
        path = t.path
        if t.kind != "torrent" and os.path.isfile(path):
            if st.get("mark_downloaded", True):
                mark_of_the_web(path, getattr(t, "final_url", "") or t.url, t.options.get("referer", ""))
            if st.get("use_server_time") and getattr(t, "last_modified", ""):
                try:
                    from email.utils import parsedate_to_datetime
                    ts = parsedate_to_datetime(t.last_modified).timestamp()
                    os.utime(path, (ts, ts))
                except (TypeError, ValueError, OSError):
                    pass
        target = path if t.kind != "torrent" else os.path.join(t.save_dir, t.name)
        if st.get("av_scan") and os.path.exists(target):
            self._scan(t, target)
        if st.get("post_cmd_enabled") and st.get("post_cmd") and os.path.exists(target):
            args = (st.get("post_cmd_args") or '"%path%"').replace("%path%", target)
            try:
                subprocess.Popen(f'"{st["post_cmd"]}" {args}', creationflags=CREATE_NO_WINDOW)
                t.logmsg(f"Programa executado: {st['post_cmd']} {args}")
            except OSError as e:
                t.logmsg(f"Falha ao executar o programa: {e}")

    def _scan(self, t, target):
        st = self.settings
        exe = st.get("av_path") or find_defender()
        if not exe:
            t.logmsg("Antivírus: nenhum encontrado (configure em Preferências › Antivírus)")
            return
        custom = st.get("av_args")
        if custom:
            cmd = f'"{exe}" {custom.replace("%path%", target)}'
        elif os.path.basename(exe).lower() == "mpcmdrun.exe":
            cmd = [exe, "-Scan", "-ScanType", "3", "-File", target, "-DisableRemediation"]
        else:
            cmd = [exe, target]
        t.logmsg(f"Verificando com o antivírus ({os.path.basename(exe)})…")
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, creationflags=CREATE_NO_WINDOW,
                               encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as e:
            t.logmsg(f"Antivírus falhou: {e}")
            return
        out = (p.stdout or "") + (p.stderr or "")
        # MpCmdRun: 0 = limpo, 2 = ameaça. Outros antivírus de linha de comando: diferente de 0 = ameaça.
        base = os.path.basename(exe).lower()
        if base == "mpcmdrun.exe":
            threat = p.returncode == 2
        elif base.startswith("clam"):             # ClamAV: 1 = vírus encontrado, 2 = erro
            threat = p.returncode == 1
        else:
            threat = p.returncode != 0
        if threat:
            t.status = ERROR
            t.retryable = False
            t.error = "⚠ " + _("Ameaça detectada pelo antivírus — não abra este arquivo")
            t.virus = True
            t.logmsg(out.strip()[-500:])
            self.events.append(("virus", t))
        else:
            t.logmsg("Antivírus: nenhuma ameaça encontrada")
        t.dirty = True

    def _watch_folder(self):
        d = self.settings.get("torrent_watch_dir")
        if not d or not os.path.isdir(d) or not lt:
            return
        for path in glob.glob(os.path.join(glob.escape(d), "*.torrent")):
            try:
                auto = bool(self.settings.get("torrent_watch_auto"))
                t = self.add_torrent_file(path, None, start=auto)
                os.replace(path, path + ".adicionado")
                t.logmsg(f"Encontrado na pasta monitorada: {path}")
                self.events.append(("info", _("Torrent adicionado da pasta monitorada: {nome}").format(nome=t.name)))
            except Exception as e:  # noqa: BLE001
                try:
                    os.replace(path, path + ".invalido")
                except OSError:
                    pass
                self.events.append(("info", _("Torrent inválido na pasta monitorada: {nome} ({erro})").format(nome=os.path.basename(path), erro=e)))

    def _schedule(self):
        st = self.settings
        if not st.get("scheduler_enabled"):
            return
        hm = time.strftime("%H:%M")
        if hm == self._sched_last:
            return
        self._sched_last = hm
        if hm == st.get("scheduler_start"):
            self.resume_all()
            self.events.append(("info", _("Agendador: downloads retomados")))
        elif hm == st.get("scheduler_stop"):
            self.pause_all()
            self.events.append(("info", _("Agendador: downloads pausados")))

    # ---------- estatísticas ----------
    def total_speed(self):
        return sum(t.speed for t in self.tasks)

    def total_up_speed(self):
        return sum(t.up_speed for t in self.tasks)

    def has_pending_work(self):
        return any(t.status in ACTIVE_STATES or t.status == QUEUED for t in self.tasks)

    # ---------- encerramento ----------
    def shutdown(self):
        with self.lock:
            tasks = list(self.tasks)
        resume = [t for t in tasks if t.status in ACTIVE_STATES or t.status == QUEUED]
        for t in tasks:
            if t.is_running():
                t.pause()
        deadline = time.time() + 6
        for t in tasks:
            t.wait(max(0.1, deadline - time.time()))
        for t in resume:
            t.status = QUEUED
        try:
            self.torrents.save_all()
        except Exception:
            pass
        self.save(force=True)
