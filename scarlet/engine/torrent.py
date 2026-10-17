"""Torrents e links magnet via libtorrent (opcional: sem a biblioteca, só esse tipo fica indisponível)."""
import os
import shutil
import time
import urllib.parse

from .task import Task, QUEUED, STARTING, DOWNLOADING, PAUSED, COMPLETED, ERROR, PROCESSING, SEEDING
from .. import VERSION
from ..i18n import _
from ..util import app_data_dir

class _LazyLibtorrent:
    """libtorrent pesa ~20 MB de RAM: só é carregado quando alguém usa torrent.
    bool(lt) diz se está disponível sem carregar; lt.algo carrega na primeira vez."""
    _mod = None
    _ok = None

    def _load(self):
        if _LazyLibtorrent._mod is None:
            import libtorrent
            _LazyLibtorrent._mod = libtorrent
        return _LazyLibtorrent._mod

    def __bool__(self):
        if _LazyLibtorrent._ok is None:
            import importlib.util
            try:
                _LazyLibtorrent._ok = importlib.util.find_spec("libtorrent") is not None
            except (ImportError, ValueError):
                _LazyLibtorrent._ok = False
        return _LazyLibtorrent._ok

    def __getattr__(self, name):
        return getattr(self._load(), name)


lt = _LazyLibtorrent()


def _flag(*names):
    """Acha uma constante do libtorrent pelo nome, entre versões 1.2/2.0/2.1."""
    for n in names:
        obj = lt
        try:
            for part in n.split("."):
                obj = getattr(obj, part)
            return obj
        except AttributeError:
            continue
    return 0


class TorrentEngine:
    def __init__(self, manager):
        self.manager = manager
        self.ses = None
        self.dir = os.path.join(app_data_dir(), "torrents")
        os.makedirs(self.dir, exist_ok=True)
        self._pending_saves = 0

    @staticmethod
    def available():
        return bool(lt)

    def ensure(self):
        if not lt:
            raise RuntimeError(_("Suporte a torrent indisponível nesta instalação"))
        if self.ses is None:
            st = self.manager.settings
            port = int(st.get("torrent_port", 6881))
            mask = (_flag("alert_category.error", "alert.category_t.error_notification")
                    | _flag("alert_category.storage", "alert.category_t.storage_notification")
                    | _flag("alert_category.status", "alert.category_t.status_notification"))
            self.ses = lt.session({
                "listen_interfaces": f"0.0.0.0:{port},[::]:{port}",
                "alert_mask": int(mask),
                "enable_dht": True,
                "enable_lsd": True,
                "enable_upnp": True,
                "enable_natpmp": True,
                "user_agent": f"ScarletDM/{VERSION} libtorrent/{lt.__version__}",
            "dht_bootstrap_nodes": "dht.libtorrent.org:25401,router.bittorrent.com:6881,"
                                   "router.utorrent.com:6881,dht.transmissionbt.com:6881",
            })
            self.apply_limits()
        return self.ses

    def apply_limits(self):
        if self.ses is None:
            return
        st = self.manager.settings
        down = int(st.get("speed_limit", 0)) if st.get("limit_enabled") else 0
        enc = {"force": 0, "prefer": 1, "off": 2}.get(st.get("torrent_encryption", "prefer"), 1)
        utp = bool(st.get("torrent_utp", True))
        upnp = bool(st.get("torrent_upnp", True))
        self.ses.apply_settings({
            "download_rate_limit": down,
            "upload_rate_limit": int(st.get("upload_limit", 0) or 0),
            "enable_dht": bool(st.get("torrent_dht", True)),
            "enable_lsd": bool(st.get("torrent_lsd", True)),
            "enable_upnp": upnp,
            "enable_natpmp": upnp,
            "enable_outgoing_utp": utp,
            "enable_incoming_utp": utp,
            "out_enc_policy": enc,
            "in_enc_policy": enc,
            "allowed_enc_level": 3,
        })

    def resume_path(self, task):
        return os.path.join(self.dir, task.id + ".fastresume")

    def pump(self):
        if self.ses is None:
            return
        for a in self.ses.pop_alerts():
            name = type(a).__name__
            if name == "save_resume_data_alert":
                self._pending_saves = max(0, self._pending_saves - 1)
                task = self._task_for(a.handle)
                if task is not None:
                    try:
                        data = lt.write_resume_data_buf(a.params)
                        with open(self.resume_path(task), "wb") as f:
                            f.write(data)
                    except Exception as e:  # noqa: BLE001
                        task.logmsg(f"Falha ao salvar dados de retomada: {e}")
            elif name == "save_resume_data_failed_alert":
                self._pending_saves = max(0, self._pending_saves - 1)
            elif name in ("metadata_received_alert",):
                task = self._task_for(a.handle)
                if task is not None:
                    task.logmsg("Metadados recebidos")
                    self.request_save(task)
            elif name.endswith("error_alert"):
                task = self._task_for(getattr(a, "handle", None))
                if task is not None:
                    task.logmsg(a.message())

    def _task_for(self, handle):
        if handle is None:
            return None
        for t in self.manager.tasks:
            if t.kind == "torrent" and t.handle is not None and t.handle == handle:
                return t
        return None

    def request_save(self, task):
        h = task.handle
        if h is None or not h.is_valid():
            return
        try:
            flags = _flag("save_resume_flags_t.save_info_dict", "torrent_handle.save_info_dict")
            h.save_resume_data(flags)
            self._pending_saves += 1
        except Exception:
            pass

    def save_all(self, timeout=5.0):
        if self.ses is None:
            return
        for t in self.manager.tasks:
            if t.kind == "torrent":
                self.request_save(t)
        end = time.time() + timeout
        while self._pending_saves > 0 and time.time() < end:
            self.ses.wait_for_alert(200)
            self.pump()


class TorrentTask(Task):
    kind = "torrent"
    reports_own_speed = True

    def __init__(self, url="", save_dir="", filename=None, options=None, id=None, torrent_file=""):
        super().__init__(url, save_dir, filename, options, id)
        self.torrent_file = torrent_file
        self.handle = None
        self.info_hash = ""
        self._name = ""
        self._done = 0
        self.peers = 0
        self.seeds = 0
        self.uploaded = 0
        self.files = []          # [(caminho, tamanho)]
        self.file_progress = []
        self.priorities = None   # lista de 0/4 por arquivo
        self.state_text = ""

    @property
    def name(self):
        if self.filename:
            return self.filename
        if self._name:
            return self._name
        if self.url.startswith("magnet:"):
            dn = urllib.parse.parse_qs(urllib.parse.urlsplit(self.url).query).get("dn")
            if dn:
                return dn[0]
        if self.torrent_file:
            return os.path.splitext(os.path.basename(self.torrent_file))[0]
        return "Torrent"

    @property
    def category(self):
        return "torrent"

    @property
    def done(self):
        return self._done

    @property
    def connections_active(self):
        return self.peers

    def is_running(self):
        return self.handle is not None and self.status in (STARTING, DOWNLOADING, PROCESSING, SEEDING)

    def _engine(self):
        return self.manager.torrents

    def _add_to_session(self):
        eng = self._engine()
        ses = eng.ensure()
        rp = eng.resume_path(self)
        atp = None
        if os.path.exists(rp):
            try:
                with open(rp, "rb") as f:
                    atp = lt.read_resume_data(f.read())
            except Exception as e:  # noqa: BLE001
                self.logmsg(f"Dados de retomada inválidos ({e}); verificando arquivos")
                atp = None
        if atp is None:
            if self.torrent_file:
                atp = lt.add_torrent_params()
                atp.ti = lt.torrent_info(self.torrent_file)
            else:
                atp = lt.parse_magnet_uri(self.url)
        atp.save_path = self.save_dir
        auto = _flag("torrent_flags.auto_managed")
        paused = _flag("torrent_flags.paused")
        if auto or paused:
            atp.flags = atp.flags & ~(auto | paused)
        os.makedirs(self.save_dir, exist_ok=True)
        self.handle = ses.add_torrent(atp)
        try:
            self.info_hash = str(self.handle.info_hashes().v1)
        except AttributeError:
            self.info_hash = str(self.handle.info_hash())
        if self.priorities:
            try:
                self.handle.prioritize_files(self.priorities)
            except Exception:
                pass
        self.logmsg(f"Adicionado à sessão de torrent ({self.info_hash})")

    def start(self):
        if self.status == COMPLETED and not self.manager.settings.get("torrent_seed"):
            return
        try:
            if self.handle is None or not self.handle.is_valid():
                self._add_to_session()
            self.handle.resume()
            self.error = ""
            self.status = STARTING
        except Exception as e:  # noqa: BLE001
            self.status = ERROR
            self.error = str(e)
            self.logmsg(f"Falhou: {e}")
        self.dirty = True

    def pause(self):
        if self.handle is not None and self.handle.is_valid():
            self.handle.pause()
            self._engine().request_save(self)
        if self.status != COMPLETED:
            self.status = PAUSED
        self.speed = self.up_speed = 0.0
        self.dirty = True

    def wait(self, timeout=None):
        pass

    def refresh(self):
        h = self.handle
        if h is None or not h.is_valid():
            self.speed = self.up_speed = 0.0
            return
        st = h.status()
        self._name = st.name or self._name
        if st.has_metadata:
            self.total = st.total_wanted
            if not self.files:
                ti = h.torrent_file()
                fs = ti.files()
                self.files = [(fs.file_path(i), fs.file_size(i)) for i in range(fs.num_files())]
                self.filename = self.filename or ti.name()
                self.dirty = True
        self._done = st.total_wanted_done
        self.uploaded = st.all_time_upload
        self.speed = float(st.download_payload_rate)
        self.up_speed = float(st.upload_payload_rate)
        self.peers = st.num_peers
        self.seeds = st.num_seeds
        try:
            self.file_progress = list(h.file_progress())
        except Exception:
            pass
        paused_flag = _flag("torrent_flags.paused")
        is_paused = bool(int(st.flags) & int(paused_flag)) if paused_flag else bool(getattr(st, "paused", False))
        if st.errc.value() != 0:
            if self.status != ERROR:
                self.status = ERROR
                self.error = st.errc.message()
                self.logmsg(f"Erro: {self.error}")
                self.dirty = True
            return
        if is_paused:
            self.speed = self.up_speed = 0.0
            return
        s = st.state
        S = lt.torrent_status.states
        if s in (S.checking_files, S.checking_resume_data):
            new, self.state_text = PROCESSING, _("Verificando arquivos")
        elif s == S.downloading_metadata:
            new, self.state_text = STARTING, _("Obtendo metadados")
        elif s in (S.finished, S.seeding) or st.is_finished:
            if self.finished is None:
                self.finished = time.time()
                self.logmsg("Download do torrent concluído")
            ratio = float(self.manager.settings.get("torrent_ratio", 0) or 0)
            reached = ratio > 0 and self.total > 0 and self.uploaded / self.total >= ratio
            if self.manager.settings.get("torrent_seed") and not reached:
                new, self.state_text = SEEDING, _("Semeando (proporção {r})").format(r=f"{self.uploaded / max(1, self.total):.2f}")
            else:
                if reached and self.status == SEEDING:
                    self.logmsg(f"Proporção {ratio} atingida; parando de semear")
                h.pause()
                self._engine().request_save(self)
                new, self.state_text = COMPLETED, ""
                self.speed = self.up_speed = 0.0
        else:
            new, self.state_text = DOWNLOADING, ""
        if new != self.status:
            self.status = new
            self.dirty = True

    def pieces(self):
        h = self.handle
        if h is None or not h.is_valid():
            return []
        try:
            return list(h.status(_flag("status_flags_t.query_pieces", "torrent_handle.query_pieces")).pieces)
        except Exception:
            return []

    def set_file_wanted(self, index, wanted):
        if not self.files:
            return
        if not self.priorities or len(self.priorities) != len(self.files):
            self.priorities = [4] * len(self.files)
        self.priorities[index] = 4 if wanted else 0
        if self.handle is not None and self.handle.is_valid():
            self.handle.prioritize_files(self.priorities)
        self.dirty = True

    def detach(self, delete_files):
        eng = self._engine()
        if self.handle is not None and self.handle.is_valid() and eng.ses is not None:
            flag = _flag("options_t.delete_files", "session.delete_files") if delete_files else 0
            try:
                eng.ses.remove_torrent(self.handle, flag)
            except Exception:
                eng.ses.remove_torrent(self.handle)
        elif delete_files:
            target = os.path.join(self.save_dir, self.name)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            elif os.path.isfile(target):
                os.remove(target)
        self.handle = None
        for p in (eng.resume_path(self),):
            if os.path.exists(p):
                os.remove(p)

    def delete_files(self, include_completed=True):
        self.detach(include_completed)

    def reset(self):
        self.detach(True)
        super().reset()
        self.files, self.file_progress, self._done = [], [], 0

    def to_dict(self):
        d = super().to_dict()
        d.update(torrent_file=self.torrent_file, info_hash=self.info_hash, name_cache=self._name,
                 files=self.files, priorities=self.priorities, done_cache=self._done)
        return d

    def load_dict(self, d):
        super().load_dict(d)
        self.torrent_file = d.get("torrent_file", "")
        self.info_hash = d.get("info_hash", "")
        self._name = d.get("name_cache", "")
        self.files = [tuple(x) for x in d.get("files", [])]
        self.priorities = d.get("priorities")
        self._done = d.get("done_cache", 0)
        if self.status == SEEDING:
            self.status = QUEUED
