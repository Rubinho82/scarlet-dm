"""Diálogos: adicionar download, preferências, excluir, desligamento automático e sobre."""
import os
import re
import secrets
import shutil
import sys
import threading
import urllib.parse

import requests
from PySide6.QtCore import Qt, QObject, QTime, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox, QStackedWidget,
                               QTimeEdit, QToolButton, QVBoxLayout, QWidget, QButtonGroup, QFrame)

from .. import APP_NAME, VERSION, autostart
from ..engine.manager import find_defender
from ..engine import components as comp
from ..engine.media_task import (VIDEO_QUALITIES, FPS_CHOICES, AUDIO_FORMATS, AUDIO_KBPS, is_drm_url, is_media_url,
                                 probe_media, ytdlp_command)
from ..i18n import _, LANGUAGES
from ..engine.torrent import lt
from ..util import (open_path, expand_batch, extract_urls, filename_from_content_disposition, filename_from_url,
                    format_eta, format_size, free_space, guess_extension, sanitize_filename, find_ffmpeg,
                    app_data_dir, parse_speed)
from .theme import C, glyph, app_icon_pixmap, apply_dark_titlebar, bring_to_front, keep_on_screen

_CR = re.compile(r"bytes\s+\d+-\d+/(\d+)")


def probe_url(url, opts, settings):
    s = requests.Session()
    mode = settings.get("proxy_mode", "none")
    s.trust_env = mode == "system"
    if mode == "manual" and settings.get("proxy_url"):
        s.proxies = {"http": settings["proxy_url"], "https": settings["proxy_url"]}
    s.verify = bool(settings.get("verify_ssl", True))
    h = {"User-Agent": opts.get("user_agent") or settings.get("user_agent"), "Accept": "*/*",
         "Accept-Encoding": "identity", "Range": "bytes=0-0"}
    if opts.get("referer"):
        h["Referer"] = opts["referer"]
    if opts.get("cookies"):
        h["Cookie"] = opts["cookies"]
    for k, v in (opts.get("headers") or {}).items():
        if k.lower() not in ("range", "accept-encoding"):
            h[k] = v
    r = s.get(url, headers=h, stream=True, timeout=(8, 15), allow_redirects=True)
    try:
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code} {r.reason}"}
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 206:
            m = _CR.search(r.headers.get("Content-Range", ""))
            size = int(m.group(1)) if m else -1
        else:
            cl = r.headers.get("Content-Length", "")
            size = int(cl) if cl.isdigit() else -1
        name = filename_from_content_disposition(r.headers.get("Content-Disposition")) or filename_from_url(r.url)
        if not os.path.splitext(name)[1]:
            name += guess_extension(ct)
        hls = "mpegurl" in ct.lower() or urllib.parse.urlsplit(r.url).path.lower().endswith(".m3u8")
        return {"name": sanitize_filename(name), "size": size, "resumable": r.status_code == 206,
                "type": ct.split(";")[0], "hls": hls, "html": ct.lower().startswith("text/html")}
    finally:
        r.close()


class _Signals(QObject):
    comps = Signal(dict)
    done = Signal(int, dict)
    media = Signal(int, dict)
    thumb = Signal(int, bytes)
    status = Signal(str, bool)


def parse_headers(text):
    out = {}
    for line in (text or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']}")
    return f


class AddDialog(QDialog):
    def __init__(self, manager, parent=None, urls=None, options=None, filename=None, torrent_files=None):
        super().__init__(parent)
        self.m = manager
        self.st = manager.settings
        self.setWindowTitle(_("Adicionar download"))
        self.setMinimumWidth(680)
        self._opts_in = dict(options or {})
        self._probe_id = 0
        self._dir_edited = False
        self._media = None            # resultado do yt-dlp para o link único
        self.torrent_files = list(torrent_files or [])
        self.sig = _Signals()
        self.sig.done.connect(self._probe_done)
        self.sig.media.connect(self._media_done)
        self.sig.thumb.connect(self._thumb_done)

        # conteúdo numa área com rolagem; os botões Baixar/Cancelar ficam fixos embaixo (telas pequenas,
        # notebooks 1366x768 e "Opções avançadas" aberto não escondem mais nada)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(22, 18, 22, 8)
        lay.setSpacing(10)
        h1 = QLabel(_("Adicionar download"))
        h1.setObjectName("H1")
        lay.addWidget(h1)

        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText(_("Cole links: arquivos (http/ftp), vídeos do YouTube/SoundCloud/Vimeo/X/Instagram…, "
                                     "magnet, .m3u8 — um por linha. Lote: foto[001-100].jpg"))
        self.urls.setFixedHeight(92)
        lay.addWidget(self.urls)

        info = QHBoxLayout()
        self.info_icon = QLabel()
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        info.addWidget(self.info_icon)
        info.addWidget(self.info, 1)
        lay.addLayout(info)

        # painel de vídeo/música (sites)
        self.media_box = QWidget()
        mb = QHBoxLayout(self.media_box)
        mb.setContentsMargins(0, 2, 0, 2)
        self.thumb = QLabel()
        self.thumb.setFixedSize(176, 99)
        self.thumb.setStyleSheet(f"background:{C['panel2']}; border-radius:6px; border:1px solid {C['border']}")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mb.addWidget(self.thumb)
        col = QVBoxLayout()
        self.media_title = QLabel("")
        self.media_title.setObjectName("H2")
        self.media_title.setWordWrap(True)
        self.media_meta = QLabel("")
        self.media_meta.setObjectName("Muted")
        qgrid = QGridLayout()
        qgrid.setHorizontalSpacing(8)
        qgrid.setVerticalSpacing(6)
        self.mode = QComboBox()
        self.mode.addItem(_("Vídeo"), "video")
        self.mode.addItem(_("Só o áudio"), "audio")
        self.quality = QComboBox()       # resolução (vídeo)
        self.fps = QComboBox()
        self.afmt = QComboBox()
        for key, label in AUDIO_FORMATS:
            self.afmt.addItem(_(label), key)
        self.kbps = QComboBox()
        for key, label in AUDIO_KBPS:
            self.kbps.addItem(_(label), key)
        for cb in (self.mode, self.quality, self.fps, self.afmt, self.kbps):
            cb.setMinimumWidth(150)
        self.l_res, self.l_fps = QLabel(_("Resolução")), QLabel("FPS")
        self.l_fmt, self.l_kbps = QLabel(_("Formato")), QLabel(_("Qualidade"))
        qgrid.addWidget(QLabel(_("Baixar como")), 0, 0)
        qgrid.addWidget(self.mode, 0, 1)
        qgrid.addWidget(self.l_res, 1, 0)
        qgrid.addWidget(self.quality, 1, 1)
        qgrid.addWidget(self.l_fps, 1, 2)
        qgrid.addWidget(self.fps, 1, 3)
        qgrid.addWidget(self.l_fmt, 2, 0)
        qgrid.addWidget(self.afmt, 2, 1)
        qgrid.addWidget(self.l_kbps, 2, 2)
        qgrid.addWidget(self.kbps, 2, 3)
        qgrid.setColumnStretch(4, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.afmt.currentIndexChanged.connect(self._mode_changed)
        col.addWidget(self.media_title)
        col.addWidget(self.media_meta)
        col.addStretch(1)
        col.addLayout(qgrid)
        mb.addLayout(col, 1)
        self.media_box.setVisible(False)
        lay.addWidget(self.media_box)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel(_("Salvar em")), 0, 0)
        self.dir = QLineEdit(self.st["download_dir"])
        self.dir.textEdited.connect(self._on_dir_edited)
        browse = QPushButton(_("Procurar…"))
        browse.clicked.connect(self._browse)
        grid.addWidget(self.dir, 0, 1)
        grid.addWidget(browse, 0, 2)
        self.space = QLabel("")
        self.space.setObjectName("Faint")
        grid.addWidget(self.space, 1, 1, 1, 2)
        self.name_label = QLabel(_("Nome do arquivo"))
        grid.addWidget(self.name_label, 2, 0)
        self.name = QLineEdit(filename or "")
        self.name.setPlaceholderText(_("automático"))
        grid.addWidget(self.name, 2, 1, 1, 2)
        grid.addWidget(QLabel(_("Conexões")), 3, 0)
        crow = QHBoxLayout()
        self.conns = QSpinBox()
        self.conns.setRange(1, 32)
        self.conns.setValue(int(self.st.get("connections", 8)))
        crow.addWidget(self.conns)
        self.start_now = QCheckBox(_("Iniciar agora"))
        self.start_now.setChecked(True)
        crow.addSpacing(16)
        crow.addWidget(self.start_now)
        crow.addStretch(1)
        grid.addLayout(crow, 3, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        self.adv_btn = QToolButton()
        self.adv_btn.setText(_("  Opções avançadas"))
        self.adv_btn.setIcon(glyph("chevron", C["muted"], 12))
        self.adv_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_btn.setCheckable(True)
        self.adv_btn.toggled.connect(self._toggle_adv)
        lay.addWidget(self.adv_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.adv = QWidget()
        af = QFormLayout(self.adv)
        af.setContentsMargins(0, 0, 0, 0)
        self.referer = QLineEdit(self._opts_in.get("referer", ""))
        self.ua = QLineEdit(self._opts_in.get("user_agent", ""))
        self.ua.setPlaceholderText(_("padrão das Preferências"))
        self.cookies = QLineEdit(self._opts_in.get("cookies", ""))
        self.cookies.setPlaceholderText(_("nome=valor; outro=valor"))
        self.headers = QPlainTextEdit("\n".join(f"{k}: {v}" for k, v in (self._opts_in.get("headers") or {}).items()))
        self.headers.setPlaceholderText(_("Authorization: Bearer …\nX-Outro: valor"))
        self.headers.setFixedHeight(64)
        cs = QHBoxLayout()
        self.cs_algo = QComboBox()
        self.cs_algo.addItems(["sha256", "sha1", "md5", "sha512"])
        self.cs_value = QLineEdit()
        self.cs_value.setPlaceholderText(_("hash esperado (opcional): verifica o arquivo ao terminar"))
        cs.addWidget(self.cs_algo)
        cs.addWidget(self.cs_value, 1)
        self.force_hls = QCheckBox(_("Tratar como stream HLS (.m3u8)"))
        self.force_hls.setChecked(self._opts_in.get("kind") == "hls")
        self.force_media = QCheckBox(_("Tratar como página de vídeo/música"))
        self.force_media.setChecked(self._opts_in.get("kind") == "media")
        self.force_media.toggled.connect(lambda _: self._on_urls_changed())
        af.addRow(_("Referer"), self.referer)
        af.addRow(_("User-Agent"), self.ua)
        af.addRow(_("Cookies"), self.cookies)
        af.addRow(_("Cabeçalhos"), self.headers)
        af.addRow(_("Checksum"), cs)
        af.addRow("", self.force_hls)
        af.addRow("", self.force_media)
        self.adv.setVisible(False)
        lay.addWidget(self.adv)

        btns = QHBoxLayout()
        tor = QPushButton(_("Abrir .torrent…"))
        tor.setIcon(glyph("torrent", C["muted"], 16))
        tor.clicked.connect(self._pick_torrent)
        tor.setEnabled(bool(lt))
        btns.addWidget(tor)
        btns.addStretch(1)
        cancel = QPushButton(_("Cancelar"))
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(_("Baixar"))
        self.ok.setObjectName("Primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        foot = QWidget()
        foot.setObjectName("DialogFoot")
        foot.setLayout(btns)
        btns.setContentsMargins(22, 10, 22, 16)
        outer.addWidget(foot)

        self._fill_quality([])
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._probe)
        self.urls.textChanged.connect(self._on_urls_changed)
        if urls:
            self.urls.setPlainText("\n".join(urls))
        self._update_space()
        self._on_urls_changed()
        if self.torrent_files:
            self._show_torrents()

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))
        QTimer.singleShot(0, self.fit_to_screen)
        QTimer.singleShot(50, lambda: bring_to_front(self))     # link vindo do navegador: aparece na frente dele
        if not self.urls.toPlainText():
            self.urls.setFocus()

    # ---------- interação ----------
    def _toggle_adv(self, on):
        self.adv.setVisible(on)
        self.adv_btn.setIcon(glyph("chevron" if not on else "up", C["muted"], 12))
        self.fit_to_screen()
        if on:   # mostra as opções que acabaram de abrir
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.adv, 0, 0))

    def fit_to_screen(self):
        """Altura do conteúdo, mas nunca maior que a tela disponível (o resto rola)."""
        self.body.adjustSize()
        screen = (self.windowHandle().screen() if self.windowHandle() else None) or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        foot_h = self.layout().itemAt(1).widget().sizeHint().height()
        want = self.body.sizeHint().height() + foot_h + 2
        h = min(want, avail.height() - 60)          # 60 = barra de título e uma folga
        self.resize(max(self.width(), self.minimumWidth()), h)
        g = self.frameGeometry()
        if g.bottom() > avail.bottom() or g.top() < avail.top():   # mantém a janela inteira dentro da tela
            self.move(g.left(), max(avail.top(), avail.bottom() - g.height()))

    def _on_dir_edited(self):
        self._dir_edited = True
        self._update_space()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, _("Escolher pasta"), self.dir.text())
        if d:
            self.dir.setText(os.path.normpath(d))
            self._dir_edited = True
            self._update_space()

    def _update_space(self):
        free = free_space(self.dir.text())
        self.space.setText(_('Espaço livre: {format_size}').format(format_size=format_size(free)) if free >= 0 else "")

    def _pick_torrent(self):
        files, _flt = QFileDialog.getOpenFileNames(self, _("Abrir torrent"), "", _("Torrent (*.torrent)"))
        if files:
            self.torrent_files += files
            self._show_torrents()

    def _show_torrents(self):
        names = ", ".join(os.path.basename(f) for f in self.torrent_files)
        self._set_info("torrent", _('{len} arquivo(s) .torrent: {names}').format(len=len(self.torrent_files), names=names))
        self.ok.setEnabled(True)

    def _raw_urls(self):
        return extract_urls(self.urls.toPlainText())

    def _urls(self):
        out = []
        for u in self._raw_urls():
            out.extend(expand_batch(u))
        return list(dict.fromkeys(out))

    def _is_media(self, u):
        return self.force_media.isChecked() or self._opts_in.get("kind") == "media" or is_media_url(u)

    def _fill_quality(self, heights, audio_only=False, has60=True):
        st = self.st
        cur = self.quality.currentData() or str(st.get("media_quality", "best"))
        if cur in ("mp3", "m4a"):
            cur = "best"
        self.quality.blockSignals(True)
        self.quality.clear()
        for key, label in VIDEO_QUALITIES:
            if key.isdigit() and heights and int(key) > max(heights):
                continue
            self.quality.addItem(_(label), key)
        i = self.quality.findData(cur)
        self.quality.setCurrentIndex(i if i >= 0 else 0)
        self.quality.blockSignals(False)
        fcur = self.fps.currentData() if self.fps.count() else str(st.get("media_fps", ""))
        self.fps.clear()
        for key, label in FPS_CHOICES:
            if key == "60" and not has60:
                continue
            self.fps.addItem(_(label), key)
        i = self.fps.findData(fcur or "")
        self.fps.setCurrentIndex(i if i >= 0 else 0)
        self.fps.setToolTip("" if has60 else _("Este vídeo não tem versão em 60 fps"))
        if self.afmt.currentIndex() < 0 or not getattr(self, "_afmt_set", False):
            self._afmt_set = True
            i = self.afmt.findData(st.get("media_audio_format", "mp3"))
            self.afmt.setCurrentIndex(max(0, i))
            i = self.kbps.findData(str(st.get("media_audio_kbps", "320")))
            self.kbps.setCurrentIndex(max(0, i))
            wanted_audio = str(st.get("media_quality", "best")) in ("mp3", "m4a", "audio")
            self.mode.setCurrentIndex(1 if wanted_audio else 0)
        if audio_only:
            self.mode.setCurrentIndex(1)
        self.mode.model().item(0).setEnabled(not audio_only)
        self._mode_changed()

    def _mode_changed(self, *_a):
        audio = self.mode.currentData() == "audio"
        for w in (self.l_res, self.quality, self.l_fps, self.fps):
            w.setVisible(not audio)
        for w in (self.l_fmt, self.afmt, self.l_kbps, self.kbps):
            w.setVisible(audio)
        self.kbps.setEnabled(self.afmt.currentData() == "mp3")
        self.kbps.setToolTip("" if self.afmt.currentData() == "mp3" else
                             _("Este formato guarda o áudio original, sem reconverter"))

    def _media_options(self):
        if self.mode.currentData() == "audio":
            return {"quality": "audio", "audio_format": self.afmt.currentData() or "mp3",
                    "audio_kbps": self.kbps.currentData() or "320"}
        return {"quality": self.quality.currentData() or "best", "fps": self.fps.currentData() or ""}

    def _set_info(self, icon, text, error=False):
        self.info_icon.setPixmap(glyph(icon, C["accent_hi"] if error else C["muted"], 16).pixmap(16, 16))
        self.info.setObjectName("Error" if error else "Muted")
        self.info.setStyleSheet("")
        self.info.style().unpolish(self.info)
        self.info.style().polish(self.info)
        self.info.setText(text)

    def _on_urls_changed(self):
        urls = self._urls()
        self._media = None
        self.ok.setEnabled(bool(urls) or bool(self.torrent_files))
        single = len(urls) == 1
        media_any = any(self._is_media(u) for u in urls)
        if self.media_box.isVisible() != media_any:
            self.media_box.setVisible(media_any)
            if self.isVisible():
                QTimer.singleShot(0, self.fit_to_screen)
        self.thumb.clear()
        self.media_title.setText("")
        self.media_meta.setText("")
        self.name.setEnabled(single and not urls[0].lower().startswith("magnet:"))
        if not urls:
            if not self.torrent_files:
                self._set_info("info", "")
            return
        drm = [u for u in urls if is_drm_url(u)]
        if drm:
            self._set_info("error", _("Spotify, Netflix, Deezer e outros com DRM (proteção contra cópia) não podem ser "
                                    "baixados. YouTube, SoundCloud, Vimeo e +1000 sites funcionam."), True)
            self.ok.setEnabled(len(drm) < len(urls))
            return
        if len(urls) > 1:
            n_raw = len(self._raw_urls())
            extra = _(" (lote expandido)") if len(urls) > n_raw else ""
            kinds = _(' · {sum} de vídeo/música').format(sum=sum(1 for u in urls if self._is_media(u))) if media_any else ""
            self._set_info("link", _('{len} links serão adicionados{extra}{kinds}').format(len=len(urls), extra=extra, kinds=kinds))
            if media_any:
                self.media_title.setText(_("Vários vídeos/músicas"))
                self.media_meta.setText(_("A qualidade escolhida vale para todos."))
                self._fill_quality([])
            return
        u = urls[0]
        if u.lower().startswith("magnet:?"):
            dn = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query).get("dn", ["(nome virá dos metadados)"])[0]
            if not lt:
                self._set_info("error", _("Torrent indisponível: instale com  pip install libtorrent"), True)
            else:
                self._set_info("torrent", _('Torrent: {dn}').format(dn=dn))
            return
        if self._is_media(u):
            self.name_label.setText(_("Nome do arquivo"))
            self._set_info("refresh", _("Lendo informações do vídeo/música…"))
            self.thumb.setText("…")
        else:
            self._set_info("refresh", _("Verificando o link…"))
        self._timer.start()

    def _probe(self):
        urls = self._urls()
        if len(urls) != 1 or urls[0].lower().startswith("magnet:"):
            return
        self._probe_id += 1
        pid = self._probe_id
        opts = self._options()
        url = urls[0]
        media = self._is_media(url)

        def work():
            if media:
                try:
                    res = probe_media(url, self.st, opts)
                except Exception as e:  # noqa: BLE001
                    res = {"error": str(e)}
                self.sig.media.emit(pid, res)
                thumb = res.get("thumbnail") if isinstance(res, dict) else ""
                if thumb:
                    try:
                        data = requests.get(thumb, timeout=10).content
                        self.sig.thumb.emit(pid, data)
                    except requests.RequestException:
                        pass
                return
            try:
                res = probe_url(url, opts, self.st)
            except requests.exceptions.SSLError:
                res = {"error": _("Erro de certificado SSL")}
            except requests.RequestException as e:
                res = {"error": _('Sem resposta do servidor ({__name__})').format(__name__=e.__class__.__name__)}
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e)}
            self.sig.done.emit(pid, res)
        threading.Thread(target=work, daemon=True).start()

    def _media_done(self, pid, res):
        if pid != self._probe_id:
            return
        if "error" in res:
            self.thumb.setText("")
            self._set_info("error", f"{res['error']}", True)
            return
        self._media = res
        if res.get("playlist"):
            self.media_title.setText(res["title"])
            self.media_meta.setText(_('Playlist com {res} itens — todos serão adicionados').format(res=res['count']))
            self.thumb.setPixmap(glyph("stream", C["accent"], 48).pixmap(48, 48))
            self._fill_quality([])
            self._set_info("check", _('Playlist: {res} itens').format(res=res['count']))
            self.name.setEnabled(False)
            return
        self.media_title.setText(res["title"])
        bits = [res.get("extractor", ""), res.get("uploader", "")]
        if res.get("duration"):
            bits.append(format_eta(res["duration"]))
        if res.get("size"):
            bits.append("~" + format_size(res["size"]))
        self.media_meta.setText(" · ".join(b for b in bits if b))
        self._fill_quality(res.get("heights") or [], res.get("audio_only"), res.get("has60", True))
        if res.get("heights"):
            top = _("até {h}p").format(h=res["heights"][0]) + (_(" · 60 fps") if res.get("has60") else "")
        else:
            top = _("só áudio")
        self._set_info("check", _("Encontrado ({detalhe}). Escolha a qualidade e clique em Baixar.").format(detalhe=top))
        if not self.name.text():
            self.name.setPlaceholderText(sanitize_filename(res["title"]))

    def _thumb_done(self, pid, data):
        if pid != self._probe_id:
            return
        pm = QPixmap()
        if pm.loadFromData(data):
            self.thumb.setPixmap(pm.scaled(self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation))

    def _probe_done(self, pid, res):
        if pid != self._probe_id:
            return
        if "error" in res:
            self._set_info("error", _('{res} — dá para adicionar mesmo assim e tentar depois').format(res=res['error']), True)
            return
        if res["hls"]:
            self.force_hls.setChecked(True)
            self._set_info("stream", _("Stream HLS (.m3u8): será baixado em pedaços e salvo como MP4"))
            return
        if res.get("html"):
            self._set_info("error", _("Esse link abre uma página da web, não um arquivo. Se for página de vídeo, marque "
                                    "“Tratar como página de vídeo” em Opções avançadas."), True)
            return
        parts = [res["name"], format_size(res["size"]) if res["size"] >= 0 else _("tamanho desconhecido"),
                 _("retomável, várias conexões") if res["resumable"] else _("sem retomada (1 conexão)")]
        if res["type"]:
            parts.append(res["type"])
        self._set_info("check", " · ".join(parts))
        if not self.name.text():
            self.name.setPlaceholderText(res["name"])
        free = free_space(self.dir.text())
        if res["size"] > 0 and 0 <= free < res["size"]:
            self._set_info("error", _('Espaço insuficiente: precisa de {format_size}, livre {format_size2}').format(format_size=format_size(res['size']), format_size2=format_size(free)), True)

    def _options(self):
        o = {}
        for key in ("title",):
            if self._opts_in.get(key):
                o[key] = self._opts_in[key]
        if self.referer.text().strip():
            o["referer"] = self.referer.text().strip()
        if self.ua.text().strip():
            o["user_agent"] = self.ua.text().strip()
        if self.cookies.text().strip():
            o["cookies"] = self.cookies.text().strip()
        hdr = parse_headers(self.headers.toPlainText())
        if hdr:
            o["headers"] = hdr
        if self.cs_value.text().strip():
            o["checksum"] = {"algo": self.cs_algo.currentText(), "value": self.cs_value.text().strip()}
        if self.conns.value() != int(self.st.get("connections", 8)):
            o["connections"] = self.conns.value()
        return o

    def _accept(self):
        d = self.dir.text().strip()
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as e:
            self._set_info("error", _('Não foi possível usar a pasta: {e}').format(e=e), True)
            return
        self.accept()

    # ---------- resultado ----------
    def result_items(self):
        """[(url, nome_ou_None, opções)]"""
        urls = [u for u in self._urls() if not is_drm_url(u)]
        opts = self._options()
        if self.force_hls.isChecked():
            opts["kind"] = "hls"
        name = self.name.text().strip() if len(urls) == 1 and self.name.isEnabled() else ""
        media_opts = self._media_options()
        items = []
        for u in urls:
            o = dict(opts)
            if self._is_media(u):
                o["kind"] = "media"
                o.update(media_opts)
                o.pop("checksum", None)
                if self._media and self._media.get("playlist") and len(urls) == 1:
                    for e in self._media["entries"]:
                        oo = dict(o, title=e.get("title") or "")
                        items.append((e["url"], None, oo))
                    continue
                if self._media and self._media.get("title") and not o.get("title"):
                    o["title"] = self._media["title"]
                if self._media and self._media.get("thumbnail"):
                    o["thumbnail"] = self._media["thumbnail"]
                if name:
                    o["title"] = os.path.splitext(name)[0]
                items.append((u, None, o))
            else:
                items.append((u, name or None, o))
        return items

    def save_dir(self):
        """None = deixa o gerenciador escolher (respeita subpastas por categoria)."""
        d = os.path.normpath(self.dir.text().strip())
        if not self._dir_edited and os.path.normcase(d) == os.path.normcase(os.path.normpath(self.st["download_dir"])):
            return None
        return d


class ConfirmDelete(QDialog):
    def __init__(self, count, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Excluir"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        t = QLabel(_('Excluir {count} download(s) da lista?').format(count=count))
        t.setObjectName("H2")
        lay.addWidget(t)
        self.files = QCheckBox(_("Excluir também os arquivos do disco"))
        lay.addWidget(self.files)
        self.remember = QCheckBox(_("Não perguntar de novo (dá para mudar em Preferências › Geral)"))
        lay.addWidget(self.remember)
        note = QLabel(_("Arquivos incompletos (.sdm) são sempre apagados."))
        note.setObjectName("Muted")
        lay.addWidget(note)
        b = QHBoxLayout()
        b.addStretch(1)
        c = QPushButton(_("Cancelar"))
        c.clicked.connect(self.reject)
        ok = QPushButton(_("Excluir"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        b.addWidget(c)
        b.addWidget(ok)
        lay.addLayout(b)

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))


class ShutdownDialog(QDialog):
    def __init__(self, seconds=60, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Desligamento automático"))
        self.left = seconds
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        t = QLabel(_("Todos os downloads terminaram."))
        t.setObjectName("H2")
        lay.addWidget(t)
        self.msg = QLabel("")
        lay.addWidget(self.msg)
        b = QHBoxLayout()
        b.addStretch(1)
        c = QPushButton(_("Cancelar"))
        c.clicked.connect(self.reject)
        now = QPushButton(_("Desligar agora"))
        now.setObjectName("Primary")
        now.clicked.connect(self.accept)
        b.addWidget(c)
        b.addWidget(now)
        lay.addLayout(b)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._tick(first=True)

    def _tick(self, first=False):
        if not first:
            self.left -= 1
        self.msg.setText(_('O computador será desligado em {left} s.').format(left=self.left))
        if self.left <= 0:
            self.timer.stop()
            self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Sobre o {APP_NAME}').format(APP_NAME=APP_NAME))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_icon_pixmap(72))
        top.addWidget(ic)
        col = QVBoxLayout()
        h = QLabel(APP_NAME)
        h.setObjectName("H1")
        col.addWidget(h)
        v = QLabel(_('Versão {VERSION}').format(VERSION=VERSION))
        v.setObjectName("Muted")
        col.addWidget(v)
        top.addLayout(col)
        top.addStretch(1)
        lay.addLayout(top)
        txt = QLabel(
            _('Gerenciador de downloads com várias conexões por arquivo, retomada, fila, limite de velocidade, agendador, vídeos e músicas de sites, streams HLS, torrents, antivírus, acesso remoto e integração com o navegador.\n\nTorrent: {__version__ifltelseindisponível}\nVídeos de sites: {prontoifytdlp_command}\nffmpeg: {find_ffmpeg}\nDados: {app_data_dir}').format(__version__ifltelseindisponível='libtorrent ' + lt.__version__ if lt else 'indisponível', prontoifytdlp_command='pronto' if ytdlp_command() else 'instalado sozinho no primeiro uso', find_ffmpeg=find_ffmpeg() or 'não encontrado', app_data_dir=app_data_dir()))
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(txt)
        ok = QPushButton(_("Fechar"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        self.setMinimumWidth(480)

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))


class SettingsDialog(QDialog):
    PAGES = ["Geral", "Downloads", "Conexões", "Velocidade", "Proxy", "Navegador", "Vídeos de sites", "Torrent",
             "Antivírus", "Notificações", "Agendador", "Acesso remoto", "Avançado"]

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.st = settings
        self.setWindowTitle(_("Preferências"))
        self.resize(960, 640)
        self.sig = _Signals()
        self.sig.comps.connect(self._components_shown)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("SideNav")
        self.nav.setFixedWidth(200)
        self.pages = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        s = settings

        # --- Geral
        f = self._page(_("Geral"), "settings")
        dir_row = QHBoxLayout()
        self.dir = QLineEdit(s["download_dir"])
        b = QPushButton(_("Procurar…"))
        b.clicked.connect(lambda: self._browse(self.dir))
        dir_row.addWidget(self.dir, 1)
        dir_row.addWidget(b)
        f.addRow(_("Pasta de downloads"), dir_row)
        self.subfolders = self._check(f, _("Separar em subpastas por tipo (Vídeo, Música, Programas…)"), "category_subfolders")
        self.on_exists = self._combo([(_("Renomear (arquivo (1).ext)"), "rename"), (_("Sobrescrever"), "overwrite")],
                                     s["on_exists"])
        f.addRow(_("Se o arquivo já existir"), self.on_exists)
        self.delete_action = self._combo([(_("Sempre perguntar"), "ask"), (_("Remover só da lista"), "list"),
                                          (_("Remover e apagar os arquivos"), "files")], s["delete_action"])
        f.addRow(_("Botão Excluir"), self.delete_action)
        f.addRow(_hline())
        self.tray_close = self._check(f, _("Ao fechar a janela, continuar na bandeja do sistema"), "close_to_tray")
        self.clip = self._check(f, _("Monitorar a área de transferência e oferecer links copiados"), "clipboard_monitor")
        self.autostart = QCheckBox(_("Iniciar com o Windows (minimizado na bandeja)"))
        self.autostart.setChecked(autostart.is_enabled())
        f.addRow("", self.autostart)
        self.prevent_sleep = self._check(f, _("Impedir que o PC entre em suspensão enquanto houver downloads"),
                                         "prevent_sleep")
        self.check_updates = self._check(f, _("Avisar quando houver versão nova do Scarlet DM"), "check_updates")
        f.addRow(_hline())
        self.language = self._combo([(_("Automático (idioma do Windows)"), "")] + [(n, c) for c, n in LANGUAGES],
                                    s.get("language", ""))
        f.addRow(_("Idioma"), self.language)
        self.compact = self._check(f, _("Lista compacta (linhas mais baixas)"), "compact")
        self.use_player = self._check(f, _("Duplo clique em vídeo/música abre no reprodutor do Scarlet"), "use_player")
        self.scale = self._combo([("100%", 100), ("110%", 110), ("125%", 125), ("150%", 150)], s["ui_scale"])
        f.addRow(_("Zoom da interface (reiniciar)"), self.scale)

        # --- Downloads
        f = self._page(_("Downloads"), "down")
        self.auto_retry = self._check(f, _("Repetir sozinho os que falharem por queda de rede (até 5x)"), "auto_retry")
        self.autoremove_missing = self._check(f, _("Remover da lista os downloads cujo arquivo foi apagado do disco"),
                                              "autoremove_missing")
        self.autoremove_completed = self._check(f, _("Remover da lista os downloads concluídos"), "autoremove_completed")
        self.skip_html = self._check(f, _("Não baixar páginas da web (avisar quando o link não for um arquivo)"),
                                     "skip_html")
        self.mark = self._check(f, _("Marcar arquivos baixados como vindos da internet (segurança do Windows)"),
                                "mark_downloaded")
        self.server_time = self._check(f, _("Usar a data do servidor no arquivo baixado"), "use_server_time")
        self.backup = self._spin(0, 168, s["backup_hours"])
        self.backup.setSuffix(" h")
        self.backup.setSpecialValueText("desligado")
        f.addRow(_("Backup da lista a cada"), self.backup)

        # --- Conexões
        f = self._page(_("Conexões"), "link")
        self.max_active = self._spin(1, 20, s["max_active"])
        f.addRow(_("Downloads simultâneos"), self.max_active)
        self.conns = self._spin(1, 32, s["connections"])
        f.addRow(_("Conexões por download"), self.conns)
        self.per_server = self._spin(1, 64, s["max_per_server"])
        f.addRow(_("Máximo por servidor"), self.per_server)
        self.total_conns = self._spin(4, 512, s["max_total_conns"])
        f.addRow(_("Máximo de conexões no total"), self.total_conns)
        self.retries = self._spin(0, 100, s["retries"])
        f.addRow(_("Tentativas por conexão"), self.retries)
        self.timeout = self._spin(5, 300, s["timeout"])
        self.timeout.setSuffix(" s")
        f.addRow(_("Tempo limite de leitura"), self.timeout)
        self.ua = QLineEdit(s["user_agent"])
        f.addRow(_("User-Agent"), self.ua)
        self.ssl = self._check(f, _("Verificar certificados SSL (recomendado)"), "verify_ssl")
        hint = QLabel(_("O Scarlet reduz as conexões sozinho quando um servidor reclama (HTTP 429/503)."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        f.addRow("", hint)

        # --- Velocidade
        f = self._page(_("Velocidade"), "speed")
        self.limit_on = self._check(f, _("Limitar a velocidade de download"), "limit_enabled")
        self.limit = self._spin(16, 10_000_000, max(16, s["speed_limit"] // 1024))
        self.limit.setSuffix(" KB/s")
        f.addRow(_("Limite de download"), self.limit)
        self.up_limit = self._spin(0, 10_000_000, s["upload_limit"] // 1024)
        self.up_limit.setSuffix(" KB/s")
        self.up_limit.setSpecialValueText(_("sem limite"))
        f.addRow(_("Limite de envio (torrent)"), self.up_limit)
        hint = QLabel(_("O botão de velocidade na barra inferior liga e desliga o limite rapidamente."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        f.addRow("", hint)

        # --- Proxy
        f = self._page(_("Proxy"), "globe")
        self.proxy_group = QButtonGroup(self)
        self.px_none = QRadioButton(_("Conexão direta (sem proxy)"))
        self.px_sys = QRadioButton(_("Usar o proxy do sistema"))
        self.px_man = QRadioButton(_("Proxy manual"))
        for i, rb in enumerate((self.px_none, self.px_sys, self.px_man)):
            self.proxy_group.addButton(rb, i)
            f.addRow("", rb)
        {"none": self.px_none, "system": self.px_sys, "manual": self.px_man}.get(s["proxy_mode"], self.px_none).setChecked(True)
        self.proxy_url = QLineEdit(s["proxy_url"])
        self.proxy_url.setPlaceholderText("http://usuario:senha@host:porta  ou  socks5://host:porta")
        f.addRow(_("Endereço"), self.proxy_url)

        # --- Navegador
        f = self._page(_("Navegador"), "globe")
        self.api_on = self._check(f, _("Receber links da extensão do navegador"), "api_enabled")
        self.api_port = self._spin(1024, 65535, s["api_port"])
        f.addRow(_("Porta local"), self.api_port)
        self.confirm = self._check(f, _("Mostrar a janela de confirmação para links vindos do navegador"),
                                   "confirm_browser_links")
        # onde fica a pasta extension/: ao lado do .exe (Windows/Linux), em Contents/Resources (app do macOS)
        # ou na raiz do código-fonte
        here = os.path.dirname(sys.executable)
        bases = [here, os.path.join(os.path.dirname(here), "Resources"), getattr(sys, "_MEIPASS", ""),
                 os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
        base = next((b for b in bases if b and os.path.isdir(os.path.join(b, "extension"))), bases[-1])
        ext_dirs = [("Chrome, Edge, Brave, Opera, Vivaldi", os.path.join(base, "extension"))]
        ff_dir = next((d for d in (os.path.join(base, "extension-firefox"), os.path.join(base, "build", "extension-firefox"))
                       if os.path.isdir(d)), "")
        if ff_dir:
            ext_dirs.append(("Firefox", ff_dir))
        how = QLabel(_("Chrome, Edge, Brave, Opera e Vivaldi: abra a página de extensões (chrome://extensions, "
                       "edge://extensions…), ligue o “Modo do desenvolvedor”, clique em “Carregar sem compactação” e "
                       "escolha a pasta “extension”.") + "\n\n" +
                     _("Firefox: abra about:debugging → “Este Firefox” → “Carregar extensão temporária” e escolha o "
                       "manifest.json da pasta “extension-firefox” (vale até fechar o Firefox; a versão permanente é a "
                       "publicada na loja de extensões da Mozilla).") + "\n\n" +
                     _("Qualquer outro navegador: deixe ligado “Monitorar a área de transferência” em Geral — copie o "
                       "link e o Scarlet oferece o download.") + "\n\n" +
                     _("Pular sites, pular extensões e o tamanho mínimo ficam no ícone da extensão."))
        how.setWordWrap(True)
        how.setObjectName("Muted")
        f.addRow("", how)
        for label, d in ext_dirs:
            open_ext = QPushButton(f"{label}:  {d}")
            open_ext.setObjectName("Link")
            open_ext.clicked.connect(lambda _c=False, d=d: open_path(d) if os.path.isdir(d) else None)
            f.addRow("", open_ext)

        # --- Vídeos de sites
        f = self._page(_("Vídeos de sites"), "video")
        self.c_ytdlp = QLabel(_("verificando…"))
        self.c_ffmpeg = QLabel(_("verificando…"))
        self.c_js = QLabel(_("verificando…"))
        f.addRow(_("Mecanismo de vídeos"), self.c_ytdlp)
        f.addRow(_("Conversor de vídeo"), self.c_ffmpeg)
        f.addRow(_("Componente do YouTube"), self.c_js)
        self.ytdlp_btn = QPushButton(_("Instalar / atualizar componentes agora"))
        self.ytdlp_btn.clicked.connect(self._update_components)
        f.addRow("", self.ytdlp_btn)
        self.ytdlp_auto = self._check(f, _("Atualizar o mecanismo toda semana (os sites mudam muito)"),
                                      "ytdlp_auto_update")
        f.addRow(_hline())
        self.media_mode = self._combo([(_("Vídeo"), "video"), (_("Só o áudio"), "audio")],
                                      "audio" if str(s["media_quality"]) in ("mp3", "m4a", "audio") else "video")
        f.addRow(_("Baixar como (padrão)"), self.media_mode)
        self.media_q = self._combo([(_(label), key) for key, label in VIDEO_QUALITIES],
                                   s["media_quality"] if str(s["media_quality"]).isdigit() else "best")
        f.addRow(_("Resolução padrão"), self.media_q)
        self.media_fps = self._combo([(_(label), key) for key, label in FPS_CHOICES], s["media_fps"])
        f.addRow(_("FPS padrão"), self.media_fps)
        self.media_afmt = self._combo([(_(label), key) for key, label in AUDIO_FORMATS], s["media_audio_format"])
        f.addRow(_("Formato de áudio padrão"), self.media_afmt)
        self.media_kbps = self._combo([(_(label), key) for key, label in AUDIO_KBPS], str(s["media_audio_kbps"]))
        f.addRow(_("Qualidade do MP3"), self.media_kbps)
        self.media_container = self._combo([(_("MP4 (toca em tudo)"), "mp4"), ("MKV", "mkv")], s["media_container"])
        f.addRow(_("Formato do vídeo"), self.media_container)
        self.media_compat = self._check(f, _("Preferir H.264/AAC (toca em TVs e celulares antigos)"), "media_compat")
        self.media_subs = self._check(f, _("Baixar e embutir legendas (português e inglês)"), "media_subs")
        drm = QLabel(_("Funciona com YouTube, YouTube Music, SoundCloud, Vimeo, X/Twitter, Instagram, TikTok, Facebook, "
                       "Twitch, Reddit, Bandcamp e +1000 sites. Serviços com DRM (Spotify, Netflix, Deezer…) não. "
                       "Baixe apenas o que você tem direito de baixar."))
        drm.setWordWrap(True)
        drm.setObjectName("Muted")
        f.addRow("", drm)
        threading.Thread(target=self._check_components, daemon=True).start()

        # --- Torrent
        f = self._page(_("Torrent"), "torrent")
        self.bt_port = self._spin(1024, 65535, s["torrent_port"])
        f.addRow(_("Porta de escuta"), self.bt_port)
        self.seed = self._check(f, _("Continuar semeando depois de concluir"), "torrent_seed")
        self.ratio = QDoubleSpinBox()
        self.ratio.setRange(0, 100)
        self.ratio.setSingleStep(0.5)
        self.ratio.setValue(float(s["torrent_ratio"]))
        self.ratio.setSpecialValueText(_("sem limite"))
        f.addRow(_("Parar de semear na proporção"), self.ratio)
        self.enc = self._combo([(_("Preferir criptografia"), "prefer"), (_("Exigir criptografia"), "force"),
                                (_("Desativada"), "off")], s["torrent_encryption"])
        f.addRow(_("Criptografia"), self.enc)
        self.dht = self._check(f, _("DHT (achar mais pares sem rastreador)"), "torrent_dht")
        self.lsd = self._check(f, _("Local Peer Discovery (pares na rede local)"), "torrent_lsd")
        self.upnp = self._check(f, _("Abrir a porta no roteador (UPnP / NAT-PMP)"), "torrent_upnp")
        self.utp = self._check(f, _("uTP (protocolo que não congestiona a rede)"), "torrent_utp")
        f.addRow(_hline())
        wrow = QHBoxLayout()
        self.watch = QLineEdit(s["torrent_watch_dir"])
        self.watch.setPlaceholderText("desligado")
        wb = QPushButton(_("Procurar…"))
        wb.clicked.connect(lambda: self._browse(self.watch))
        wrow.addWidget(self.watch, 1)
        wrow.addWidget(wb)
        f.addRow(_("Monitorar pasta de .torrent"), wrow)
        self.watch_auto = self._check(f, _("Iniciar sem confirmação os torrents encontrados na pasta"),
                                      "torrent_watch_auto")
        self.del_src = self._check(f, _("Apagar o arquivo .torrent original quando o download concluir"),
                                   "torrent_delete_source")
        assoc = QPushButton(_("Usar o Scarlet DM para links magnet e arquivos .torrent"))
        assoc.clicked.connect(self._associate)
        f.addRow("", assoc)
        st_lbl = QLabel(f"libtorrent {lt.__version__}" if lt else _("libtorrent não instalado (pip install libtorrent)"))
        st_lbl.setObjectName("Muted")
        f.addRow(_("Motor"), st_lbl)

        # --- Antivírus
        f = self._page(_("Antivírus"), "check")
        self.av = self._check(f, _("Verificar cada arquivo com o antivírus quando o download terminar"), "av_scan")
        arow = QHBoxLayout()
        self.av_path = QLineEdit(s["av_path"])
        defender = find_defender()
        self.av_path.setPlaceholderText(_('automático: {defender}').format(defender=defender) if defender else _("caminho do antivírus (.exe)"))
        ab = QPushButton(_("Procurar…"))
        ab.clicked.connect(lambda: self._browse_file(self.av_path, _("Programas (*.exe)")))
        arow.addWidget(self.av_path, 1)
        arow.addWidget(ab)
        f.addRow(_("Programa"), arow)
        self.av_args = QLineEdit(s["av_args"])
        self.av_args.setPlaceholderText(_("automático para o Windows Defender; use %path% para o arquivo"))
        f.addRow(_("Argumentos"), self.av_args)
        av_hint = QLabel(_("Se encontrar ameaça, o download fica marcado em vermelho e você recebe um aviso."))
        av_hint.setObjectName("Muted")
        av_hint.setWordWrap(True)
        f.addRow("", av_hint)

        # --- Notificações
        f = self._page(_("Notificações"), "info")
        self.notify = self._check(f, _("Avisar quando um download terminar"), "notify_complete")
        self.notify_added = self._check(f, _("Avisar quando um download for adicionado"), "notify_added")
        self.notify_errors = self._check(f, _("Avisar quando um download falhar"), "notify_errors")
        self.notify_inactive = self._check(f, _("Só avisar quando a janela do Scarlet não estiver em foco"),
                                           "notify_only_inactive")
        self.notify_sound = self._check(f, _("Tocar um som junto com o aviso"), "notify_sound")

        # --- Agendador
        f = self._page(_("Agendador"), "calendar")
        self.sched = self._check(f, _("Usar agendador diário"), "scheduler_enabled")
        self.sched_start = QTimeEdit(QTime.fromString(s["scheduler_start"], "HH:mm"))
        self.sched_start.setDisplayFormat("HH:mm")
        self.sched_stop = QTimeEdit(QTime.fromString(s["scheduler_stop"], "HH:mm"))
        self.sched_stop.setDisplayFormat("HH:mm")
        f.addRow(_("Retomar todos às"), self.sched_start)
        f.addRow(_("Pausar todos às"), self.sched_stop)
        sh = QLabel(_("Útil para baixar de madrugada, quando a internet está livre."))
        sh.setObjectName("Muted")
        f.addRow("", sh)

        # --- Acesso remoto
        f = self._page(_("Acesso remoto"), "globe")
        self.remote = self._check(f, _("Permitir controlar os downloads pelo celular ou outro PC na mesma rede"),
                                  "remote_enabled")
        self.remote_port = self._spin(1024, 65535, s["remote_port"])
        f.addRow(_("Porta"), self.remote_port)
        prow = QHBoxLayout()
        self.remote_pw = QLineEdit(s["remote_password"] or secrets.token_urlsafe(9))
        gen = QPushButton(_("Gerar nova"))
        gen.clicked.connect(lambda: self.remote_pw.setText(secrets.token_urlsafe(9)))
        prow.addWidget(self.remote_pw, 1)
        prow.addWidget(gen)
        f.addRow(_("Senha"), prow)
        rh = QLabel(_("Depois de salvar, o endereço aparece no chip “Remoto” da barra inferior. "
                    "O Windows pode pedir para liberar o firewall na primeira vez."))
        rh.setObjectName("Muted")
        rh.setWordWrap(True)
        f.addRow("", rh)

        # --- Avançado
        f = self._page(_("Avançado"), "settings")
        ff_row = QHBoxLayout()
        self.ffmpeg = QLineEdit(s["ffmpeg_path"])
        self.ffmpeg.setPlaceholderText(find_ffmpeg() or _("não encontrado — streams ficarão em .ts"))
        bf = QPushButton(_("Procurar…"))
        bf.clicked.connect(lambda: self._browse_file(self.ffmpeg, _("ffmpeg (ffmpeg.exe);;Executáveis (*.exe)")))
        ff_row.addWidget(self.ffmpeg, 1)
        ff_row.addWidget(bf)
        f.addRow("ffmpeg", ff_row)
        self.hls_q = self._combo([(_("Melhor qualidade disponível"), "best"), (_("Menor tamanho"), "worst")],
                                 s["hls_quality"])
        f.addRow(_("Qualidade de streams .m3u8"), self.hls_q)
        f.addRow(_hline())
        self.post_on = self._check(f, _("Executar um programa quando um download terminar"), "post_cmd_enabled")
        prow = QHBoxLayout()
        self.post_cmd = QLineEdit(s["post_cmd"])
        pb = QPushButton(_("Procurar…"))
        pb.clicked.connect(lambda: self._browse_file(self.post_cmd, _("Programas (*.exe *.bat *.cmd);;Todos (*.*)")))
        prow.addWidget(self.post_cmd, 1)
        prow.addWidget(pb)
        f.addRow(_("Programa"), prow)
        self.post_args = QLineEdit(s["post_cmd_args"])
        f.addRow(_("Argumentos (%path%)"), self.post_args)
        f.addRow(_hline())
        data = QPushButton(app_data_dir())
        data.setObjectName("Link")
        data.clicked.connect(lambda: open_path(app_data_dir()))
        f.addRow(_("Pasta de dados"), data)

        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        foot = QWidget()
        foot.setObjectName("StatusBar")
        foot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.addStretch(1)
        c = QPushButton(_("Cancelar"))
        c.clicked.connect(self.reject)
        ok = QPushButton(_("Salvar"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self._save)
        fl.addWidget(c)
        fl.addWidget(ok)
        outer.addWidget(foot)

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))

    # ---------- construção ----------
    def _page(self, title, icon):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        h = QLabel(title)
        h.setObjectName("H1")
        lay.addWidget(h)
        lay.addSpacing(8)
        f = QFormLayout()
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(10)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(f)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(w)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pages.addWidget(scroll)
        self.nav.addItem(QListWidgetItem(glyph(icon, C["muted"], 16), "  " + title))
        return f

    def _check(self, form, text, key):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.st.get(key)))
        form.addRow("", cb)
        return cb

    @staticmethod
    def _combo(items, current):
        cb = QComboBox()
        for label, data in items:
            cb.addItem(label, data)
        i = cb.findData(current)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.setMinimumWidth(240)
        return cb

    @staticmethod
    def _spin(lo, hi, val):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(int(val))
        sp.setMinimumWidth(130)
        return sp

    def _browse(self, line):
        d = QFileDialog.getExistingDirectory(self, _("Escolher pasta"), line.text())
        if d:
            line.setText(os.path.normpath(d))

    def _browse_file(self, line, flt):
        f, _flt = QFileDialog.getOpenFileName(self, _("Escolher programa"), "", flt)
        if f:
            line.setText(os.path.normpath(f))

    # ---------- ações ----------
    def _check_components(self):
        self.sig.comps.emit({"ytdlp": comp.ytdlp_version(), "ffmpeg": comp.ffmpeg_version(),
                             "js": comp.js_version(), "done": False})

    def _components_shown(self, info):
        missing = _("não instalado — baixa sozinho quando precisar")
        for lbl, key in ((self.c_ytdlp, "ytdlp"), (self.c_ffmpeg, "ffmpeg"), (self.c_js, "js")):
            v = info.get(key)
            if isinstance(v, str) and v.startswith("!"):
                lbl.setText(v[1:])
                lbl.setObjectName("Error")
            else:
                lbl.setText((_("versão {v} ✓").format(v=v)) if v else missing)
                lbl.setObjectName("" if v else "Muted")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        if info.get("done"):
            self.ytdlp_btn.setEnabled(True)
            self.ytdlp_btn.setText(_("Instalar / atualizar componentes agora"))
        elif info.get("progress"):
            self.ytdlp_btn.setText(info["progress"])

    def _update_components(self):
        self.ytdlp_btn.setEnabled(False)

        def work():
            res = {"done": True}
            steps = [("ytdlp", _("Mecanismo de vídeos"), comp.install_ytdlp, True),
                     ("ffmpeg", _("Conversor de vídeo"), comp.install_ffmpeg, not comp.ffmpeg_path()),
                     ("js", _("Componente do YouTube"), comp.install_deno, not comp.js_runtime()[0])]
            for key, label, fn, needed in steps:
                if not needed:
                    continue
                try:
                    fn(lambda d, t, lb=label: self.sig.comps.emit(
                        {"progress": f"{lb}: {d * 100 // max(1, t)}%", "done": False}))
                except Exception as e:  # noqa: BLE001
                    res[key] = "!" + _("erro: {erro}").format(erro=str(e)[:100])
            import time as _t
            self.st["ytdlp_last_update"] = _t.time()
            res.setdefault("ytdlp", comp.ytdlp_version())
            res.setdefault("ffmpeg", comp.ffmpeg_version())
            res.setdefault("js", comp.js_version())
            self.sig.comps.emit(res)
        threading.Thread(target=work, daemon=True).start()

    def _associate(self):
        from PySide6.QtWidgets import QMessageBox
        try:
            autostart.register_handlers()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, _('Não foi possível registrar: {e}').format(e=e))
            return
        if sys.platform != "win32":
            QMessageBox.information(self, APP_NAME, _("Registrado."))
            return
        r = QMessageBox.question(self, APP_NAME, _("Registrado. Se outro programa já era o padrão, o Windows pede para "
                                                 "confirmar em Aplicativos padrão. Abrir essa tela agora?"))
        if r == QMessageBox.StandardButton.Yes:
            open_path("ms-settings:defaultapps")

    def _save(self):
        s = self.st
        s["download_dir"] = self.dir.text().strip() or s["download_dir"]
        checks = {
            "category_subfolders": self.subfolders, "close_to_tray": self.tray_close, "clipboard_monitor": self.clip,
            "prevent_sleep": self.prevent_sleep, "check_updates": self.check_updates, "compact": self.compact, "auto_retry": self.auto_retry,
            "use_player": self.use_player,
            "autoremove_missing": self.autoremove_missing, "autoremove_completed": self.autoremove_completed,
            "skip_html": self.skip_html, "mark_downloaded": self.mark, "use_server_time": self.server_time,
            "verify_ssl": self.ssl, "limit_enabled": self.limit_on, "api_enabled": self.api_on,
            "confirm_browser_links": self.confirm, "ytdlp_auto_update": self.ytdlp_auto,
            "media_compat": self.media_compat, "media_subs": self.media_subs, "torrent_seed": self.seed,
            "torrent_dht": self.dht, "torrent_lsd": self.lsd, "torrent_upnp": self.upnp, "torrent_utp": self.utp,
            "torrent_watch_auto": self.watch_auto, "torrent_delete_source": self.del_src, "av_scan": self.av,
            "notify_complete": self.notify, "notify_added": self.notify_added, "notify_errors": self.notify_errors,
            "notify_only_inactive": self.notify_inactive, "notify_sound": self.notify_sound,
            "scheduler_enabled": self.sched, "remote_enabled": self.remote, "post_cmd_enabled": self.post_on,
        }
        for key, cb in checks.items():
            s[key] = cb.isChecked()
        old_lang = s.get("language", "")
        combos = {"language": self.language, "on_exists": self.on_exists, "delete_action": self.delete_action, "ui_scale": self.scale,
                  "media_fps": self.media_fps, "media_audio_format": self.media_afmt,
                  "media_audio_kbps": self.media_kbps, "media_container": self.media_container,
                  "torrent_encryption": self.enc, "hls_quality": self.hls_q}
        for key, cb in combos.items():
            s[key] = cb.currentData()
        s["media_quality"] = "audio" if self.media_mode.currentData() == "audio" else self.media_q.currentData()
        s["backup_hours"] = self.backup.value()
        s["max_active"] = self.max_active.value()
        s["connections"] = self.conns.value()
        s["max_per_server"] = self.per_server.value()
        s["max_total_conns"] = self.total_conns.value()
        s["retries"] = self.retries.value()
        s["timeout"] = self.timeout.value()
        s["user_agent"] = self.ua.text().strip() or s["user_agent"]
        s["speed_limit"] = self.limit.value() * 1024
        s["upload_limit"] = self.up_limit.value() * 1024
        s["proxy_mode"] = ["none", "system", "manual"][max(0, self.proxy_group.checkedId())]
        s["proxy_url"] = self.proxy_url.text().strip()
        s["api_port"] = self.api_port.value()
        s["torrent_port"] = self.bt_port.value()
        s["torrent_ratio"] = self.ratio.value()
        s["torrent_watch_dir"] = self.watch.text().strip()
        s["av_path"] = self.av_path.text().strip()
        s["av_args"] = self.av_args.text().strip()
        s["scheduler_start"] = self.sched_start.time().toString("HH:mm")
        s["scheduler_stop"] = self.sched_stop.time().toString("HH:mm")
        s["remote_port"] = self.remote_port.value()
        s["remote_password"] = self.remote_pw.text().strip() or secrets.token_urlsafe(9)
        s["ffmpeg_path"] = self.ffmpeg.text().strip()
        s["post_cmd"] = self.post_cmd.text().strip()
        s["post_cmd_args"] = self.post_args.text().strip() or '"%path%"'
        try:
            autostart.set_enabled(self.autostart.isChecked())
        except OSError:
            pass
        s.save()
        if s.get("language", "") != old_lang:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, APP_NAME, _("O novo idioma será usado na próxima vez que o Scarlet DM abrir."))
        self.accept()


def ask_speed(parent, current):
    """Pequeno diálogo para digitar um limite personalizado."""
    d = QDialog(parent)
    d.setWindowTitle(_("Limite de velocidade"))
    lay = QVBoxLayout(d)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.addWidget(QLabel(_("Velocidade máxima (ex.: 750 KB, 3 MB):")))
    e = QLineEdit(format_size(current))
    lay.addWidget(e)
    b = QHBoxLayout()
    b.addStretch(1)
    c = QPushButton(_("Cancelar"))
    c.clicked.connect(d.reject)
    ok = QPushButton(_("Aplicar"))
    ok.setObjectName("Primary")
    ok.clicked.connect(d.accept)
    b.addWidget(c)
    b.addWidget(ok)
    lay.addLayout(b)
    apply_dark_titlebar(d)
    if d.exec() == QDialog.DialogCode.Accepted:
        return parse_speed(e.text())
    return None
