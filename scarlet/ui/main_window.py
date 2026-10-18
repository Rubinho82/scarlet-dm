"""Janela principal do Scarlet DM."""
import base64
import hashlib
import os
import subprocess
import sys
import threading

from PySide6.QtCore import Qt, QByteArray, QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSplitter, QSystemTrayIcon, QTableView, QToolButton, QVBoxLayout, QWidget)

import time

from .. import APP_NAME
from ..api import ApiBridge, ApiServer
from ..remote import RemoteBridge, RemoteServer
from ..engine.media_task import update_ytdlp, is_media_url
from ..engine.task import (ACTIVE_STATES, COMPLETED, QUEUED, PAUSED, ERROR, SEEDING)
from ..util import (extract_urls, is_downloadable_url, filename_from_url, format_size, format_speed, free_space,
                    looks_like_url, open_path, reveal_in_folder, keep_awake, trim_memory)
from .details import DetailsPanel
from .dialogs import AboutDialog, AddDialog, ConfirmDelete, SettingsDialog, ShutdownDialog, ask_speed
from .model import (COL_ADDED, COL_ETA, COL_NAME, COL_PROGRESS, COL_SIZE, COL_SPEED, COL_STATUS, FILTERS,
                    DownloadsModel, FilterProxy, ProgressDelegate, TaskRole, matches)
from ..i18n import _
from .theme import C, apply_dark_titlebar, app_icon, glyph, keep_on_screen
from .thumbs import ThumbService, is_playable
from .widgets import FilterBar

ARCHIVE_EXTS = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".cab", ".iso")
STORED_EXTS = {"zip", "rar", "7z", "gz", "xz", "bz2", "zst", "mp4", "mkv", "webm", "mp3", "m4a", "aac", "ogg", "opus",
               "jpg", "jpeg", "png", "gif", "webp", "avi", "mov", "flac", "iso", "msi", "exe", "apk", "pdf", "docx",
               "xlsx", "pptx", "epub"}


class _HashSignal(QObject):
    done = Signal(str, str, str)


class _UpdateSignal(QObject):
    result = Signal(object, str, bool)     # info do lançamento (ou None), erro, verificação manual?


class _JobSignal(QObject):
    progress = Signal(str)
    done = Signal(str, str)      # mensagem, caminho para abrir (ou "")


class MainWindow(QMainWindow):
    def __init__(self, settings, manager, start_hidden=False):
        super().__init__()
        self.st = settings
        self.m = manager
        self._quitting = False
        self._shutdown_done = False
        self._tray_action = None
        self._tray_hint_shown = False
        self._own_clip = None
        self._last_clip = ""
        self._had_work = False
        self._add_dlg = None
        self._disk_tick = 0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1200, 740)
        self.setMinimumSize(780, 460)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._build_tray()
        self._build_shortcuts()

        self.hash_sig = _HashSignal()
        self.hash_sig.done.connect(self._hash_done)
        self.api_bridge = ApiBridge()
        self.api_bridge.received.connect(self._on_api)
        self.api = ApiServer(self.api_bridge)
        self._apply_api()
        self.remote_bridge = RemoteBridge()
        self.remote_bridge.action.connect(self._on_remote)
        self.remote = RemoteServer(self.m, self.remote_bridge)
        self._apply_remote()
        self._awake = False
        self._apply_view()
        QTimer.singleShot(8000, self._auto_update_ytdlp)
        self._upd_sig = _UpdateSignal()
        self._upd_sig.result.connect(self._update_result)
        QTimer.singleShot(6000, lambda: self.check_app_update(manual=False))

        QApplication.clipboard().dataChanged.connect(self._on_clipboard)
        self._last_clip = QApplication.clipboard().text() or ""

        self._restore_state()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self._tick()
        self._update_actions()

    # ======================================================================= UI
    def _tool(self, icon, tip, slot, size=20, color=None, name=None):
        b = QToolButton()
        b.setIcon(glyph(icon, color or C["text"], size, hover=None))
        b.setIconSize(b.iconSize().__class__(size, size))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setAutoRaise(True)
        if name:
            b.setObjectName(name)
        if slot:
            b.clicked.connect(slot)
        return b

    def _chip(self, icon, text="", tip="", checkable=False, color=None):
        b = QToolButton()
        b.setObjectName("StatusChip")
        b.setIcon(glyph(icon, color or C["muted"], 14))
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _build_ui(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        top = QWidget()
        top.setObjectName("TopBar")
        top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(top)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(4)
        self.btn_add = self._tool("add", _("Adicionar download (Ctrl+N)"), lambda: self.open_add_dialog(), 22,
                                  "#ffffff", "AddButton")
        self.btn_add.setFixedSize(46, 40)
        h.addWidget(self.btn_add)
        h.addSpacing(10)
        self.btn_start = self._tool("play", _("Iniciar / retomar (Espaço)"), self.start_selected)
        self.btn_pause = self._tool("pause", _("Pausar (Espaço)"), self.pause_selected)
        self.btn_delete = self._tool("delete", _("Excluir (Del)"), self.delete_selected)
        self.btn_folder = self._tool("folder", _("Abrir pasta"), self.open_folder_selected)
        for b in (self.btn_start, self.btn_pause, self.btn_delete, self.btn_folder):
            b.setFixedSize(40, 40)
            h.addWidget(b)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{C['border']}")
        h.addSpacing(6)
        h.addWidget(sep)
        h.addSpacing(6)
        self.btn_resume_all = self._tool("refresh", _("Retomar todos"), self.m_resume_all)
        self.btn_pause_all = self._tool("power", _("Pausar todos"), self.m_pause_all)
        for b in (self.btn_resume_all, self.btn_pause_all):
            b.setFixedSize(40, 40)
            h.addWidget(b)
        h.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(_("Pesquisar downloads…"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.addAction(glyph("search", C["muted"], 14), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._on_search)
        h.addWidget(self.search)
        h.addSpacing(6)
        self.btn_settings = self._tool("settings", _("Preferências (Ctrl+,)"), self.open_settings)
        self.btn_menu = self._tool("menu", _("Menu"), None)
        self.btn_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        for b in (self.btn_settings, self.btn_menu):
            b.setFixedSize(40, 40)
            h.addWidget(b)
        v.addWidget(top)

        # faixa de aviso (link copiado etc.)
        self.banner = QWidget()
        self.banner.setObjectName("Banner")
        self.banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(16, 6, 10, 6)
        self.banner_icon = QLabel()
        self.banner_icon.setPixmap(glyph("link", C["accent_hi"], 16).pixmap(16, 16))
        self.banner_text = QLabel("")
        self.banner_btn = QPushButton(_("Baixar"))
        self.banner_btn.setObjectName("Primary")
        self.banner_close = self._tool("close", _("Dispensar"), lambda: self.banner.hide(), 12, C["muted"])
        bl.addWidget(self.banner_icon)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.banner_btn)
        bl.addWidget(self.banner_close)
        self.banner.hide()
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self.banner.hide)
        self._banner_action = None
        self.banner_btn.clicked.connect(self._banner_clicked)
        v.addWidget(self.banner)

        self.filters = FilterBar(FILTERS, always={"all", "active", "completed"})
        self.filters.changed.connect(self._on_filter)
        v.addWidget(self.filters)

        self.thumbs = ThumbService(self.st, self)
        self.player = None
        self.job = _JobSignal()
        self.job.progress.connect(lambda text: self.banner_show("archive", text, None, None, timeout=600000))
        self.job.done.connect(self._job_done)
        self.model = DownloadsModel(self.m, self)
        self.model.thumbs = self.thumbs
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_ADDED, Qt.SortOrder.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setIconSize(self.table.iconSize().__class__(34, 26))
        self.table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self.table))
        self.table.setMouseTracking(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col, w in ((COL_STATUS, 190), (COL_PROGRESS, 150), (COL_SPEED, 100), (COL_ETA, 90),
                       (COL_SIZE, 95), (COL_ADDED, 100)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(col, w)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)

        self.empty = QLabel(_("Nenhum download por aqui.\nClique em  +  , cole um link (Ctrl+V) ou arraste links para a janela."),
                            self.table.viewport())
        self.empty.setObjectName("Empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.viewport().installEventFilter(self)

        self.details = DetailsPanel(self.m, self.thumbs)
        self.details.action.connect(self._detail_action)
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.addWidget(self.table)
        self.split.addWidget(self.details)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setHandleWidth(1)
        self.split.setSizes([480, 230])
        v.addWidget(self.split, 1)

        sb = QWidget()
        sb.setObjectName("StatusBar")
        sb.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(10, 4, 10, 4)
        sl.setSpacing(6)
        self.chip_down = self._chip("down", "0 B/s", _("Velocidade total de download"), color=C["accent_hi"])
        self.chip_up = self._chip("up", "0 B/s", _("Velocidade total de envio (torrents)"))
        self.btn_limit = self._chip("speed", _("Sem limite"), _("Clique para ligar/desligar o limite de velocidade"),
                                    checkable=True)
        self.btn_limit.clicked.connect(self.toggle_limit)
        self.btn_limit_menu = QToolButton()
        self.btn_limit_menu.setObjectName("StatusChip")
        self.btn_limit_menu.setIcon(glyph("chevron", C["muted"], 10))
        self.btn_limit_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_limit_menu.setToolTip(_("Escolher o limite"))
        self.btn_limit_menu.setMenu(self._limit_menu())
        self.lbl_active = QLabel("")
        self.lbl_active.setObjectName("Muted")
        self.lbl_disk = QLabel("")
        self.lbl_disk.setObjectName("Faint")
        self.chip_browser = self._chip("globe", _("Navegador"), _("Integração com o navegador"))
        self.chip_browser.clicked.connect(lambda: self.open_settings(page=5))
        self.chip_remote = self._chip("link", _("Remoto"), _("Acesso remoto pelo celular — clique para copiar o endereço"))
        self.chip_remote.clicked.connect(self._copy_remote)
        self.chip_details = self._chip("info", _("Detalhes"), _("Mostrar/ocultar o painel de detalhes"), checkable=True)
        self.chip_details.toggled.connect(self._toggle_details)
        sl.addWidget(self.chip_down)
        sl.addWidget(self.chip_up)
        sl.addSpacing(6)
        sl.addWidget(self.btn_limit)
        sl.addWidget(self.btn_limit_menu)
        sl.addSpacing(10)
        sl.addWidget(self.lbl_active)
        sl.addStretch(1)
        sl.addWidget(self.lbl_disk)
        sl.addSpacing(8)
        sl.addWidget(self.chip_remote)
        sl.addWidget(self.chip_browser)
        sl.addWidget(self.chip_details)
        v.addWidget(sb)
        self.setCentralWidget(central)

    def _limit_menu(self):
        menu = QMenu(self)
        for label, val in (("128 KB/s", 128), ("256 KB/s", 256), ("512 KB/s", 512), ("1 MB/s", 1024),
                           ("2 MB/s", 2048), ("5 MB/s", 5120), ("10 MB/s", 10240), ("20 MB/s", 20480),
                           ("50 MB/s", 51200)):
            a = menu.addAction(label)
            a.triggered.connect(lambda _=False, v=val: self.set_limit(v * 1024))
        menu.addSeparator()
        custom = menu.addAction(_("Personalizado…"))
        custom.triggered.connect(self._custom_limit)
        off = menu.addAction(_("Sem limite"))
        off.triggered.connect(lambda: self.set_limit(None))
        return menu

    def _build_menu(self):
        menu = QMenu(self)
        menu.addAction(glyph("add", C["muted"], 16), _("Adicionar download…\tCtrl+N"), lambda: self.open_add_dialog())
        menu.addAction(glyph("paste", C["muted"], 16), _("Colar links da área de transferência\tCtrl+V"), self.paste_links)
        menu.addAction(glyph("import", C["muted"], 16), _("Importar links de arquivo…"), self.import_links)
        menu.addAction(glyph("torrent", C["muted"], 16), _("Abrir arquivo .torrent…"), self.open_torrent_files)
        menu.addSeparator()
        menu.addAction(glyph("save", C["muted"], 16), _("Exportar links…"), self.export_links)
        menu.addSeparator()
        menu.addAction(glyph("refresh", C["muted"], 16), _("Retomar todos"), self.m_resume_all)
        menu.addAction(glyph("pause", C["muted"], 16), _("Pausar todos"), self.m_pause_all)
        menu.addAction(glyph("check", C["muted"], 16), _("Limpar concluídos da lista"), self.clear_completed)
        menu.addSeparator()
        self.act_limit = menu.addAction(_("Limitar velocidade"))
        self.act_limit.setCheckable(True)
        self.act_limit.triggered.connect(lambda on: self.toggle_limit(on))
        self.act_shutdown = menu.addAction(_("Desligar o PC quando tudo terminar"))
        self.act_shutdown.setCheckable(True)
        self.act_shutdown.toggled.connect(self._shutdown_toggled)
        menu.addSeparator()
        menu.addAction(glyph("settings", C["muted"], 16), _("Preferências…\tCtrl+,"), self.open_settings)
        menu.addAction(glyph("refresh", C["muted"], 16), _("Procurar atualizações"),
                       lambda: self.check_app_update(manual=True))
        menu.addAction(glyph("info", C["muted"], 16), _("Sobre"), lambda: AboutDialog(self).exec())
        menu.addSeparator()
        menu.addAction(glyph("close", C["muted"], 16), _("Sair\tCtrl+Q"), self.quit_app)
        self.btn_menu.setMenu(menu)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        menu.addAction(_("Mostrar janela"), self.show_window)
        menu.addAction(_("Adicionar download…"), lambda: (self.show_window(), self.open_add_dialog()))
        menu.addAction(_("Colar links"), lambda: (self.show_window(), self.paste_links()))
        menu.addSeparator()
        menu.addAction(_("Retomar todos"), self.m_resume_all)
        menu.addAction(_("Pausar todos"), self.m_pause_all)
        self.tray_limit = menu.addAction(_("Limitar velocidade"))
        self.tray_limit.setCheckable(True)
        self.tray_limit.triggered.connect(lambda on: self.toggle_limit(on))
        menu.addSeparator()
        menu.addAction(_("Sair"), self.quit_app)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self._tray_message_clicked)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _build_shortcuts(self):
        def sc(seq, slot, widget=None, ctx=Qt.ShortcutContext.WindowShortcut):
            s = QShortcut(QKeySequence(seq), widget or self)
            s.setContext(ctx)
            s.activated.connect(slot)
            return s
        sc("Ctrl+N", lambda: self.open_add_dialog())
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+,", self.open_settings)
        sc("Ctrl+Q", self.quit_app)
        sc("Ctrl+O", self.open_torrent_files)
        w = Qt.ShortcutContext.WidgetShortcut
        sc(QKeySequence.StandardKey.Paste, self.paste_links, self.table, w)
        sc("Delete", self.delete_selected, self.table, w)
        sc("Space", self.toggle_selected, self.table, w)
        sc("Return", self.open_selected, self.table, w)
        sc("Ctrl+Shift+C", self.copy_links, self.table, w)

    # =================================================================== estado
    def _restore_state(self):
        g = self.st.get("window_geometry")
        if g:
            self.restoreGeometry(QByteArray(base64.b64decode(g)))
        sp = self.st.get("splitter_state")
        if sp:
            self.split.restoreState(QByteArray(base64.b64decode(sp)))
        hs = self.st.get("header_state")
        if hs:
            self.table.horizontalHeader().restoreState(QByteArray(base64.b64decode(hs)))
            self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        key = self.st.get("filter", "all")
        self.proxy.set_key(key)
        self.filters.select(key)
        vis = bool(self.st.get("details_visible", True))
        self.chip_details.setChecked(vis)
        self.details.setVisible(vis)
        self._sync_limit_ui()

    def _save_state(self):
        enc = lambda b: base64.b64encode(bytes(b)).decode("ascii")  # noqa: E731
        self.st["window_geometry"] = enc(self.saveGeometry())
        self.st["splitter_state"] = enc(self.split.saveState())
        self.st["header_state"] = enc(self.table.horizontalHeader().saveState())
        self.st["filter"] = self.proxy.key
        self.st["details_visible"] = self.chip_details.isChecked()
        try:
            self.st.save()
        except OSError:
            pass

    # =================================================================== ciclo
    def _tick(self):
        try:
            self.m.tick()
        except Exception as e:  # noqa: BLE001 - o laço da interface não pode morrer
            print("tick:", e, file=sys.stderr)
        tasks = list(self.m.tasks)
        n_act = sum(1 for t in tasks if t.status in ACTIVE_STATES)
        # ritmo adaptativo: 0,5 s baixando, 1 s parado, 2 s escondido na bandeja
        visible = self.isVisible() and not self.isMinimized()
        interval = 500 if (n_act and visible) else (1000 if visible else 2000)
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        if not visible:
            self._tick_hidden(tasks, n_act)
            return
        sel_ids = [t.id for t in self.selected_tasks()]
        cur = self.table.currentIndex().data(TaskRole)
        if self.model.refresh():
            self._reselect(sel_ids, cur.id if cur else None)
        state_sig = tuple((t.status, t.missing, t.category) for t in tasks)
        if state_sig != getattr(self, "_state_sig", None):
            self._state_sig = state_sig
            counts = {key: sum(1 for t in tasks if matches(t, key)) for key, _ in FILTERS}
            self.filters.update_counts(counts, self.proxy.key)
        down, up = self.m.total_speed(), self.m.total_up_speed()
        self.chip_down.setText(format_speed(down) or "0 B/s")
        self.chip_up.setText(format_speed(up) or "0 B/s")
        self.chip_up.setVisible(any(t.kind == "torrent" for t in tasks))
        n_q = sum(1 for t in tasks if t.status == QUEUED)
        parts = []
        if n_act:
            parts.append(f"{n_act} ativo{'s' if n_act > 1 else ''}")
        if n_q:
            parts.append(_('{n_q} na fila').format(n_q=n_q))
        self.lbl_active.setText(" · ".join(parts))
        self._disk_tick -= 1
        if self._disk_tick <= 0:
            self._disk_tick = 10
            free = free_space(self.st["download_dir"])
            self.lbl_disk.setText(_('Livre: {format_size}').format(format_size=format_size(free)) if free >= 0 else "")
        title = APP_NAME
        if down > 0:
            title = f"↓ {format_speed(down)} — {APP_NAME}"
        self.setWindowTitle(title)
        self.tray.setToolTip(f"{APP_NAME}\n↓ {format_speed(down) or '0 B/s'}" +
                             (f"   ↑ {format_speed(up)}" if up else "") +
                             (_('\n{n_act} ativo(s), {n_q} na fila').format(n_act=n_act, n_q=n_q) if n_act or n_q else ""))
        self.empty.setVisible(self.proxy.rowCount() == 0)
        if self.empty.isVisible():
            self.empty.setText(_("Nenhum resultado para a pesquisa.") if self.proxy.text else
                               _("Nenhum download por aqui.\nClique em  +  , cole um link (Ctrl+V) ou arraste links para a janela."))
            self.empty.resize(self.table.viewport().size())
        self.details.refresh()
        self._update_actions()
        self._process_events()
        self._check_shutdown()
        want_awake = bool(self.st.get("prevent_sleep", True)) and n_act > 0
        if want_awake != self._awake:
            self._awake = want_awake
            keep_awake(want_awake)

    def _tick_hidden(self, tasks, n_act):
        """Janela escondida: só o essencial (avisos, bandeja, desligamento, impedir suspensão)."""
        down, up = self.m.total_speed(), self.m.total_up_speed()
        n_q = sum(1 for t in tasks if t.status == QUEUED)
        self.tray.setToolTip(f"{APP_NAME}\n↓ {format_speed(down) or '0 B/s'}" +
                             (f"   ↑ {format_speed(up)}" if up else "") +
                             (_('\n{n_act} ativo(s), {n_q} na fila').format(n_act=n_act, n_q=n_q) if n_act or n_q else ""))
        self._process_events()
        self._check_shutdown()
        want_awake = bool(self.st.get("prevent_sleep", True)) and n_act > 0
        if want_awake != self._awake:
            self._awake = want_awake
            keep_awake(want_awake)

    def _reselect(self, ids, current_id):
        if not ids:
            return
        sm = self.table.selectionModel()
        idset = set(ids)
        first = None
        for row in range(self.proxy.rowCount()):
            idx = self.proxy.index(row, 0)
            t = idx.data(TaskRole)
            if t is not None and t.id in idset:
                sm.select(idx, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
                if t.id == current_id or first is None:
                    first = idx
        if first is not None:
            sm.setCurrentIndex(first, sm.SelectionFlag.NoUpdate)

    def _process_events(self):
        while self.m.events:
            kind, obj = self.m.events.popleft()
            if kind == "completed" and self.st.get("notify_complete"):
                path = obj.path
                self._notify(_("Download concluído"), obj.name, lambda p=path: reveal_in_folder(p))
            elif kind == "error" and self.st.get("notify_errors", True) and not getattr(obj, "virus", False):
                self._notify(_("Falha no download"), f"{obj.name}\n{obj.error}", self.show_window)
            elif kind == "virus":
                self._notify(_("⚠ Ameaça detectada"), _('{name}\nO antivírus encontrou uma ameaça. Não abra o arquivo.').format(name=obj.name),
                             self.show_window, force=True)
            elif kind == "info":
                self._notify(APP_NAME, obj, None)

    def _notify(self, title, text, action, force=False):
        if not self.tray.isVisible():
            return
        if not force and self.st.get("notify_only_inactive") and self.isActiveWindow():
            return
        self._tray_action = action
        self.tray.showMessage(title, text, app_icon(), 6000)
        if self.st.get("notify_sound"):
            QApplication.beep()

    def _check_shutdown(self):
        if not self.act_shutdown.isChecked():
            return
        if self.m.has_pending_work():
            self._had_work = True
            return
        if not self._had_work:
            return
        self._had_work = False
        self.act_shutdown.setChecked(False)
        self.show_window()
        dlg = ShutdownDialog(60, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._final_shutdown()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32":
                cmd = ["shutdown", "/s", "/t", "5"]
            elif sys.platform == "darwin":
                cmd = ["osascript", "-e", 'tell application "System Events" to shut down']
            else:
                cmd = ["systemctl", "poweroff"]
            try:
                subprocess.Popen(cmd, creationflags=flags)
            except OSError:
                pass
            self.quit_app()

    def _shutdown_toggled(self, on):
        self._had_work = on and self.m.has_pending_work()
        if on:
            self.banner_show("power", _("O computador será desligado quando todos os downloads terminarem."), None, None)

    # ================================================================ seleção
    def selected_tasks(self):
        out, seen = [], set()
        for idx in self.table.selectionModel().selectedRows():
            t = idx.data(TaskRole)
            if t is not None and t.id not in seen:
                seen.add(t.id)
                out.append(t)
        return out

    def _on_selection(self, *_):
        sel = self.selected_tasks()
        self.details.set_selection(sel)
        self._update_actions()

    def _update_actions(self):
        sel = self.selected_tasks()
        can_start = any(t.status in (PAUSED, ERROR, QUEUED) or (t.kind == "torrent" and t.status == COMPLETED
                        and self.st.get("torrent_seed")) for t in sel)
        can_pause = any(t.status in ACTIVE_STATES or t.status in (QUEUED, SEEDING) for t in sel)
        self.btn_start.setEnabled(can_start)
        self.btn_pause.setEnabled(can_pause)
        self.btn_delete.setEnabled(bool(sel))
        self.btn_folder.setEnabled(True)

    def _on_filter(self, key):
        self.proxy.set_key(key)
        self.filters.select(key)
        self._tick()

    def _on_search(self, text):
        self.proxy.set_text(text)
        self.empty.setVisible(self.proxy.rowCount() == 0)

    def _toggle_details(self, on):
        self.details.setVisible(on)
        if on:
            self.details.refresh(force=True)

    def eventFilter(self, obj, ev):
        if obj is self.table.viewport() and ev.type() == QEvent.Type.Resize:
            self.empty.resize(ev.size())
        return super().eventFilter(obj, ev)

    # ================================================================== ações
    def start_selected(self):
        for t in self.selected_tasks():
            if t.status in (PAUSED, ERROR, QUEUED) or t.kind == "torrent":
                self.m.start(t)
        self._tick()

    def pause_selected(self):
        for t in self.selected_tasks():
            if t.status in ACTIVE_STATES or t.status in (QUEUED, SEEDING):
                self.m.pause(t)
        self._tick()

    def toggle_selected(self):
        sel = self.selected_tasks()
        if any(t.status in ACTIVE_STATES or t.status in (QUEUED, SEEDING) for t in sel):
            self.pause_selected()
        else:
            self.start_selected()

    def delete_selected(self):
        sel = self.selected_tasks()
        if not sel:
            return
        action = self.st.get("delete_action", "ask")
        if action == "ask":
            dlg = ConfirmDelete(len(sel), self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            delete_files = dlg.files.isChecked()
            if dlg.remember.isChecked():
                self.st["delete_action"] = "files" if delete_files else "list"
                self.st.save()
        else:
            delete_files = action == "files"
        self.m.remove(sel, delete_files=delete_files)
        self.details.set_task(None)
        self._tick()

    def open_folder_selected(self):
        sel = self.selected_tasks()
        if sel:
            t = sel[0]
            reveal_in_folder(t.path if os.path.exists(t.path) else os.path.join(t.save_dir, ""))
        else:
            d = self.st["download_dir"]
            os.makedirs(d, exist_ok=True)
            open_path(d)

    def open_selected(self):
        sel = self.selected_tasks()
        if len(sel) == 1:
            self._on_double_click(self.table.currentIndex())

    def _on_double_click(self, idx):
        t = idx.data(TaskRole) if idx.isValid() else None
        if t is None:
            return
        if t.status == COMPLETED:
            if os.path.exists(t.path) and is_playable(t) and self.st.get("use_player", True):
                self._ensure_player().play_items([(t.path, t.name, t)])
            elif os.path.exists(self._target(t)):
                open_path(self._target(t))
            else:
                QMessageBox.information(self, APP_NAME, _("O arquivo não está mais no disco.\n"
                                                        "Use “Reiniciar” para baixar de novo."))
        elif t.status in ACTIVE_STATES or t.status in (QUEUED, SEEDING):
            self.m.pause(t)
        else:
            self.m.start(t)
        self._tick()

    def m_resume_all(self):
        self.m.resume_all()
        self._tick()

    def m_pause_all(self):
        self.m.pause_all()
        self._tick()

    def clear_completed(self):
        done = [t for t in self.m.tasks if t.status == COMPLETED]
        if done:
            self.m.remove(done, delete_files=False)
            self._tick()

    def copy_links(self):
        links = [t.url for t in self.selected_tasks() if t.url]
        if links:
            text = "\n".join(links)
            self._own_clip = text
            QApplication.clipboard().setText(text)

    def _context_menu(self, pos):
        sel = self.selected_tasks()
        if not sel:
            return
        t = sel[0]
        menu = QMenu(self)
        single = len(sel) == 1
        done = [x for x in sel if x.status == COMPLETED and (os.path.exists(x.path) or x.kind == "torrent")]
        playable = [x for x in done if is_playable(x)]
        if playable:
            menu.addAction(glyph("play", C["accent_hi"], 16),
                           _("Reproduzir") if len(playable) == 1 else _("Reproduzir {n} mídias").format(n=len(playable)),
                           self.play_selected)
        if single and t.status == COMPLETED and os.path.exists(t.path):
            menu.addAction(glyph("open", C["muted"], 16), _("Abrir"), lambda: open_path(t.path))
            menu.addAction(glyph("open", C["muted"], 16), _("Abrir com…"), lambda: self._open_with(t.path))
            if t.path.lower().endswith(ARCHIVE_EXTS):
                menu.addAction(glyph("archive", C["muted"], 16), _("Extrair aqui"), lambda: self._extract(t))
        menu.addAction(glyph("folder", C["muted"], 16), _("Abrir pasta"), self.open_folder_selected)
        if done:
            menu.addAction(glyph("archive", C["muted"], 16),
                           _("Compactar em ZIP…") if len(done) > 1 else _("Compactar em ZIP…"), self.zip_selected)
            menu.addAction(glyph("folder", C["muted"], 16), _("Mover para pasta…"), self.move_selected)
        menu.addSeparator()
        if any(x.status in (PAUSED, ERROR, QUEUED) for x in sel):
            menu.addAction(glyph("play", C["muted"], 16), _("Iniciar agora"), self.start_selected)
        if any(x.status in ACTIVE_STATES or x.status in (QUEUED, SEEDING) for x in sel):
            menu.addAction(glyph("pause", C["muted"], 16), _("Pausar"), self.pause_selected)
        menu.addAction(glyph("refresh", C["muted"], 16), _("Reiniciar do zero"), lambda: self._restart(sel))
        if single and t.kind in ("http", "hls"):
            menu.addAction(glyph("edit", C["muted"], 16), _("Alterar link…"), lambda: self._change_url(t))
        if any(x.url for x in sel):
            menu.addAction(glyph("copy", C["muted"], 16), _("Copiar link\tCtrl+Shift+C"), self.copy_links)
        if single and t.kind == "http" and t.status == COMPLETED and os.path.exists(t.path):
            hm = menu.addMenu(glyph("check", C["muted"], 16), _("Calcular hash"))
            for algo in ("md5", "sha1", "sha256", "sha512"):
                hm.addAction(algo.upper(), lambda a=algo: self._calc_hash(t, a))
        menu.addSeparator()
        menu.addAction(glyph("top", C["muted"], 16), _("Mover para o topo da fila"), lambda: self._move(sel, True))
        menu.addAction(glyph("bottom", C["muted"], 16), _("Mover para o fim da fila"), lambda: self._move(sel, False))
        menu.addSeparator()
        menu.addAction(glyph("delete", C["accent_hi"], 16), _("Excluir…\tDel"), self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ======================================================= mídia e arquivos
    @staticmethod
    def _target(t):
        """Arquivo (ou pasta, no caso de torrent) que um download concluído produziu."""
        return os.path.join(t.save_dir, t.name) if t.kind == "torrent" else t.path

    def _done_tasks(self):
        return [t for t in self.selected_tasks() if t.status == COMPLETED and os.path.exists(self._target(t))]

    def _ensure_player(self):
        if self.player is None:
            from .player import PlayerWindow      # importa o QtMultimedia só quando precisa
            self.player = PlayerWindow(self.thumbs)
        return self.player

    def play_selected(self):
        items = [(t.path, t.name, t) for t in self._done_tasks() if is_playable(t)]
        if items:
            self._ensure_player().play_items(items)

    def _detail_action(self, act):
        sel = self.selected_tasks()
        if act in ("play", "play_all"):
            self.play_selected()
        elif act == "open" and sel:
            target = self._target(sel[0])
            if os.path.exists(target):
                open_path(target)
        elif act == "folder":
            self.open_folder_selected()
        elif act == "copy":
            self.copy_links()
        elif act == "zip":
            self.zip_selected()
        elif act == "move":
            self.move_selected()

    def _open_with(self, path):
        if sys.platform != "win32":       # sem diálogo "Abrir com" padrão no Linux/macOS: mostra o arquivo na pasta
            reveal_in_folder(path)
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.normpath(path)], creationflags=flags)

    def zip_selected(self):
        tasks = self._done_tasks()
        if not tasks:
            return
        base = os.path.splitext(tasks[0].name)[0] if len(tasks) == 1 else time.strftime("Scarlet-%Y%m%d-%H%M%S")
        default = os.path.join(os.path.dirname(self._target(tasks[0])), base + ".zip")
        dest, _flt = QFileDialog.getSaveFileName(self, _("Compactar em ZIP"), default, _("ZIP (*.zip)"))
        if not dest:
            return
        targets = [self._target(t) for t in tasks]
        threading.Thread(target=self._zip_work, args=(targets, dest), daemon=True).start()

    def _zip_work(self, targets, dest):
        import zipfile
        try:
            files, used = [], set()
            for p in targets:
                if os.path.isdir(p):
                    root = os.path.dirname(p)
                    for dirpath, _dirs, names in os.walk(p):
                        for n in names:
                            fp = os.path.join(dirpath, n)
                            files.append((fp, os.path.relpath(fp, root)))
                else:
                    files.append((p, os.path.basename(p)))
            total = sum(os.path.getsize(fp) for fp, _ in files) or 1
            done, last = 0, 0.0
            tmp = dest + ".part"
            with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
                for fp, arc in files:
                    stem, ext = os.path.splitext(arc)
                    i = 1
                    while arc.lower() in used:
                        arc = f"{stem} ({i}){ext}"
                        i += 1
                    used.add(arc.lower())
                    zi = zipfile.ZipInfo.from_file(fp, arc)
                    zi.compress_type = (zipfile.ZIP_STORED if ext.lstrip(".").lower() in STORED_EXTS
                                        else zipfile.ZIP_DEFLATED)
                    with open(fp, "rb") as src, z.open(zi, "w", force_zip64=True) as dst:
                        for block in iter(lambda: src.read(1024 * 1024), b""):
                            dst.write(block)
                            done += len(block)
                            if time.time() - last > 0.4:
                                last = time.time()
                                self.job.progress.emit(_('Compactando {len} arquivo(s)… {done100total}% ({format_size} de {format_size2})').format(len=len(files), done100total=done * 100 // total, format_size=format_size(done), format_size2=format_size(total)))
            os.replace(tmp, dest)
            self.job.done.emit(_('ZIP criado: {basename} ({format_size})').format(basename=os.path.basename(dest), format_size=format_size(os.path.getsize(dest))), dest)
        except Exception as e:  # noqa: BLE001
            try:
                os.remove(dest + ".part")
            except OSError:
                pass
            self.job.done.emit(_('Falha ao compactar: {e}').format(e=e), "")

    def move_selected(self):
        tasks = self._done_tasks()
        if not tasks:
            return
        d = QFileDialog.getExistingDirectory(self, _("Mover para a pasta"), self.st["download_dir"])
        if not d:
            return
        d = os.path.normpath(d)
        threading.Thread(target=self._move_work, args=(tasks, d), daemon=True).start()

    def _move_work(self, tasks, d):
        import shutil
        from ..util import unique_path
        moved, last_path = 0, ""
        try:
            for i, t in enumerate(tasks, 1):
                src = self._target(t)
                if os.path.normcase(os.path.dirname(src)) == os.path.normcase(d):
                    continue
                self.job.progress.emit(_('Movendo {i}/{len}: {name}…').format(i=i, len=len(tasks), name=t.name))
                if t.kind == "torrent" and t.handle is not None and t.handle.is_valid():
                    t.handle.move_storage(d)
                    dst = os.path.join(d, t.name)
                else:
                    dst = unique_path(os.path.join(d, os.path.basename(src)))
                    shutil.move(src, dst)
                    t.filename = os.path.basename(dst)
                t.save_dir = d
                t.dirty = True
                t.logmsg(f"Movido para {dst}")
                self.thumbs.forget(t)
                moved += 1
                last_path = dst
            self.m._structure_dirty = True
            self.job.done.emit(_('{moved} item(ns) movido(s) para {d}').format(moved=moved, d=d), last_path)
        except Exception as e:  # noqa: BLE001
            self.job.done.emit(_('Falha ao mover: {e}').format(e=e), "")

    def _extract(self, t):
        from ..util import unique_path
        src = t.path
        name = os.path.basename(src)
        for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if name.lower().endswith(ext):
                name = name[: -len(ext)]
                break
        else:
            name = os.path.splitext(name)[0]
        out = unique_path(os.path.join(os.path.dirname(src), name))
        threading.Thread(target=self._extract_work, args=(src, out), daemon=True).start()

    def _extract_work(self, src, out):
        import shutil
        import tarfile
        import zipfile
        try:
            self.job.progress.emit(_('Extraindo {basename}…').format(basename=os.path.basename(src)))
            low = src.lower()
            if low.endswith(".zip") and zipfile.is_zipfile(src):
                with zipfile.ZipFile(src) as z:
                    z.extractall(out)          # o zipfile já descarta caminhos absolutos e ".."
            elif tarfile.is_tarfile(src):
                with tarfile.open(src) as tf:
                    base = os.path.realpath(out)
                    safe = [m for m in tf.getmembers() if not (m.issym() or m.islnk() or m.isdev())
                            and os.path.realpath(os.path.join(out, m.name)).startswith(base + os.sep)]
                    tf.extractall(out, members=safe)
            else:
                seven = shutil.which("7z") or next((p for p in (r"C:\Program Files\7-Zip\7z.exe",
                                                                r"C:\Program Files (x86)\7-Zip\7z.exe")
                                                    if os.path.exists(p)), "")
                if not seven:
                    raise RuntimeError(_("para .rar/.7z/.iso instale o 7-Zip (7-zip.org)"))
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                p = subprocess.run([seven, "x", "-y", f"-o{out}", src], capture_output=True, text=True,
                                   creationflags=flags, encoding="utf-8", errors="replace")
                if p.returncode not in (0, 1):
                    raise RuntimeError((p.stderr or p.stdout).strip()[-300:])
            n = sum(len(f) for _, _, f in os.walk(out))
            self.job.done.emit(_('Extraído: {n} arquivo(s) em {out}').format(n=n, out=out), out)
        except Exception as e:  # noqa: BLE001
            self.job.done.emit(_('Falha ao extrair: {e}').format(e=e), "")

    def _job_done(self, msg, path):
        if path:
            self.banner_show("check", msg, _("Abrir pasta"), lambda: reveal_in_folder(path))
        else:
            self.banner_show("error", msg, None, None)
        self._tick()

    def _restart(self, tasks):
        if QMessageBox.question(self, _("Reiniciar"), _('Baixar {len} download(s) do zero? O progresso atual será descartado.').format(len=len(tasks))) != QMessageBox.StandardButton.Yes:
            return
        for t in tasks:
            self.m.restart(t)

    def _change_url(self, t):
        d = QDialog(self)
        d.setWindowTitle(_("Alterar link"))
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 16, 20, 16)
        lab = QLabel(_("Novo link (útil quando o antigo expirou). O progresso é mantido se o arquivo for o mesmo."))
        lab.setWordWrap(True)
        lay.addWidget(lab)
        e = QLineEdit(t.url)
        e.setMinimumWidth(520)
        lay.addWidget(e)
        b = QHBoxLayout()
        b.addStretch(1)
        c = QPushButton(_("Cancelar"))
        c.clicked.connect(d.reject)
        ok = QPushButton(_("Salvar"))
        ok.setObjectName("Primary")
        ok.clicked.connect(d.accept)
        b.addWidget(c)
        b.addWidget(ok)
        lay.addLayout(b)
        apply_dark_titlebar(d)
        if d.exec() == QDialog.DialogCode.Accepted and looks_like_url(e.text()):
            running = t.is_running()
            if running:
                t.pause()
                t.wait(5)
            self.m.change_url(t, e.text())
            if running:
                self.m.start(t)

    def _calc_hash(self, t, algo):
        self.banner_show("check", _('Calculando {upper} de {name}…').format(upper=algo.upper(), name=t.name), None, None)

        def work():
            h = hashlib.new(algo)
            try:
                with open(t.path, "rb") as f:
                    for block in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(block)
                self.hash_sig.done.emit(t.name, algo, h.hexdigest())
            except OSError as e:
                self.hash_sig.done.emit(t.name, algo, _('erro: {e}').format(e=e))
        threading.Thread(target=work, daemon=True).start()

    def _hash_done(self, name, algo, value):
        self.banner.hide()
        self._own_clip = value
        QApplication.clipboard().setText(value)
        box = QMessageBox(self)
        box.setWindowTitle(f"{algo.upper()} — {name}")
        box.setText(_('{upper} de {name}:\n\n{value}\n\n(copiado para a área de transferência)').format(upper=algo.upper(), name=name, value=value))
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.exec()

    def _move(self, tasks, top):
        with self.m.lock:
            rest = [t for t in self.m.tasks if t not in tasks]
            self.m.tasks[:] = (tasks + rest) if top else (rest + tasks)
        self.m._structure_dirty = True
        self._tick()

    # ============================================================= adicionar
    def open_add_dialog(self, urls=None, options=None, filename=None, torrent_files=None):
        if self._add_dlg is not None:
            # já tem uma janela aberta: junta os links nela
            if urls:
                cur = self._add_dlg.urls.toPlainText().strip()
                self._add_dlg.urls.setPlainText((cur + "\n" if cur else "") + "\n".join(urls))
            if torrent_files:
                self._add_dlg.torrent_files += list(torrent_files)
                self._add_dlg._show_torrents()
            self._add_dlg.raise_()
            self._add_dlg.activateWindow()
            return
        dlg = AddDialog(self.m, self, urls, options, filename, torrent_files)
        self._add_dlg = dlg
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            items = dlg.result_items()
            save_dir = dlg.save_dir()
            start = dlg.start_now.isChecked()
            dups = [u for u, _, _ in items if self.m.find_duplicate(u)]
            if dups:
                r = QMessageBox.question(
                    self, _("Já está na lista"),
                    _('{len} link(s) já estão na lista. Adicionar de novo mesmo assim?').format(len=len(dups)),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if r != QMessageBox.StandardButton.Yes:
                    items = [it for it in items if it[0] not in dups]
            added = []
            for url, name, opts in items:
                added.append(self.m.add(url, save_dir, name, opts, start))
            for tf in dlg.torrent_files:
                try:
                    added.append(self.m.add_torrent_file(tf, save_dir, start))
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(self, APP_NAME, _('Não foi possível abrir {basename}:\n{e}').format(basename=os.path.basename(tf), e=e))
            if added:
                if self.st.get("notify_added"):
                    self._notify(_("Download adicionado"), added[0].name if len(added) == 1
                                 else _('{len} downloads adicionados').format(len=len(added)), self.show_window)
                if not all(matches(t, self.proxy.key) for t in added):
                    self._on_filter("all")
                self._tick()
                self._select_ids({t.id for t in added})
        finally:
            self._add_dlg = None

    def _select_ids(self, ids):
        sm = self.table.selectionModel()
        sm.clearSelection()
        for row in range(self.proxy.rowCount()):
            idx = self.proxy.index(row, 0)
            t = idx.data(TaskRole)
            if t is not None and t.id in ids:
                sm.select(idx, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
                self.table.scrollTo(idx)

    def paste_links(self):
        urls = extract_urls(QApplication.clipboard().text() or "")
        if urls:
            self.open_add_dialog(urls)
        else:
            self.banner_show("info", _("Nenhum link na área de transferência."), None, None)

    def import_links(self):
        f, _flt = QFileDialog.getOpenFileName(self, _("Importar links"), "", _("Texto (*.txt *.csv *.html *.htm);;Todos (*.*)"))
        if not f:
            return
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                urls = extract_urls(fh.read())
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if urls:
            self.open_add_dialog(urls)
        else:
            QMessageBox.information(self, APP_NAME, _("Nenhum link encontrado no arquivo."))

    def export_links(self):
        tasks = self.selected_tasks() or list(self.m.tasks)
        links = [t.url for t in tasks if t.url]
        if not links:
            return
        f, _flt = QFileDialog.getSaveFileName(self, _("Exportar links"), "links.txt", _("Texto (*.txt)"))
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("\n".join(links) + "\n")
            self.banner_show("check", _('{len} link(s) exportados para {f}').format(len=len(links), f=f), None, None)

    def open_torrent_files(self):
        files, _flt = QFileDialog.getOpenFileNames(self, _("Abrir torrent"), "", _("Torrent (*.torrent)"))
        if files:
            self.open_add_dialog(torrent_files=files)

    # ============================================================ velocidade
    def _sync_limit_ui(self):
        on = bool(self.st.get("limit_enabled"))
        self.btn_limit.setChecked(on)
        self.btn_limit.setText(_('Limite: {format_size}/s').format(format_size=format_size(self.st['speed_limit'])) if on else _("Sem limite"))
        self.btn_limit.setIcon(glyph("speed", C["accent_hi"] if on else C["muted"], 14))
        self.act_limit.setChecked(on)
        self.tray_limit.setChecked(on)

    def toggle_limit(self, on=None):
        self.st["limit_enabled"] = (not self.st.get("limit_enabled")) if on is None else bool(on)
        if isinstance(on, bool) and self.sender() is self.btn_limit:
            self.st["limit_enabled"] = on
        self.m.apply_limits()
        self._sync_limit_ui()
        self.st.save()

    def set_limit(self, value):
        if value is None:
            self.st["limit_enabled"] = False
        else:
            self.st["speed_limit"] = int(value)
            self.st["limit_enabled"] = True
        self.m.apply_limits()
        self._sync_limit_ui()
        self.st.save()

    def _custom_limit(self):
        v = ask_speed(self, self.st["speed_limit"])
        if v:
            self.set_limit(max(1024, v))

    # ========================================================== preferências
    def open_settings(self, page=0):
        dlg = SettingsDialog(self.st, self)
        if isinstance(page, int) and page:
            dlg.nav.setCurrentRow(page)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.m.apply_limits()
            self._sync_limit_ui()
            self._apply_api()
            self._apply_remote()
            self._apply_view()
            self._disk_tick = 0
            self._tick()

    def _apply_view(self):
        self.table.verticalHeader().setDefaultSectionSize(28 if self.st.get("compact") else 38)

    # ======================================================= acesso remoto
    def _apply_remote(self):
        want = bool(self.st.get("remote_enabled"))
        port = int(self.st.get("remote_port", 47332))
        pw = self.st.get("remote_password") or ""
        if want and pw and not (self.remote.running() and self.remote.port == port and self.remote.password == pw):
            self.remote.start(port, pw)
        elif not want:
            self.remote.stop()
        self.chip_remote.setVisible(want)
        if want and self.remote.running():
            self.chip_remote.setText(_('Remoto: {url}').format(url=self.remote.url()))
            self.chip_remote.setIcon(glyph("link", C["accent_hi"], 14))
        elif want:
            self.chip_remote.setText(_("Remoto: porta ocupada"))
            self.chip_remote.setToolTip(self.remote.error)

    def _copy_remote(self):
        if self.remote.running():
            self._own_clip = self.remote.url()
            QApplication.clipboard().setText(self.remote.url())
            self.banner_show("link", _('Endereço copiado: {url} — abra no navegador do celular (mesmo Wi-Fi) e use a senha das Preferências.').format(url=self.remote.url()), None, None)

    def _on_remote(self, msg):
        act = msg.get("action")
        if act == "add":
            for u in msg.get("urls", []):
                self.m.add(u, None, None, {}, True)
        elif act in ("pause", "start"):
            t = next((x for x in self.m.tasks if x.id == msg.get("id")), None)
            if t is not None:
                (self.m.pause if act == "pause" else self.m.start)(t)
        elif act == "pause_all":
            self.m.pause_all()
        elif act == "resume_all":
            self.m.resume_all()
        self._tick()

    # ========================================================= atualização do próprio app
    def check_app_update(self, manual=False):
        """Pergunta ao GitHub se há versão nova (automático: no máximo 1x a cada 20 h)."""
        if not manual:
            if not self.st.get("check_updates", True):
                return
            if time.time() - float(self.st.get("update_last_check", 0) or 0) < 20 * 3600:
                return

        def work():
            from .. import updater
            try:
                info = updater.check()
                self.st["update_last_check"] = time.time()
                self._upd_sig.result.emit(info, "", manual)
            except Exception as e:  # noqa: BLE001 - sem internet etc.
                self._upd_sig.result.emit(None, str(e), manual)
        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, info, err, manual):
        from .. import VERSION, updater
        if err or not info:
            if manual:
                QMessageBox.warning(self, APP_NAME, _("Não foi possível procurar atualizações agora: {e}")
                                    .format(e=err or "?"))
            return
        if not updater.is_newer(info["version"]):
            if manual:
                QMessageBox.information(self, APP_NAME, _("Você já está na versão mais recente ({v}).").format(v=VERSION))
            return
        if not manual and info["version"] == self.st.get("update_skip"):
            return
        self._update_info = info
        text = _("Nova versão {v} do Scarlet DM disponível.").format(v=info["version"])
        if manual or self.isVisible():
            if manual:
                self._show_update()
            else:
                self.banner_show("refresh", text, _("Atualizar"), self._show_update, timeout=10 * 60 * 1000)
        else:
            self._notify(text, _("Clique para atualizar."), lambda: (self.show_window(), self._show_update()), force=True)

    def _show_update(self):
        from .update_dialog import UpdateDialog
        UpdateDialog(self._update_info, self.st, self, quit_app=self.quit_app).exec()

    # ========================================================= yt-dlp
    def _auto_update_ytdlp(self):
        if not self.st.get("ytdlp_auto_update", True):
            return
        if time.time() - float(self.st.get("ytdlp_last_update", 0) or 0) < 7 * 86400:
            return

        def work():
            try:
                update_ytdlp(log=lambda m: None)
                self.st["ytdlp_last_update"] = time.time()
            except Exception as e:  # noqa: BLE001 - sem internet etc.: tenta de novo na próxima abertura
                print("atualização do yt-dlp falhou:", e, file=sys.stderr)
        threading.Thread(target=work, daemon=True).start()

    def _apply_api(self):
        want = bool(self.st.get("api_enabled"))
        port = int(self.st.get("api_port"))
        if want and not (self.api.running() and self.api.port == port):
            self.api.start(port)
        elif not want:
            self.api.stop()
        if not want:
            self.chip_browser.setText(_("Navegador: desligado"))
            self.chip_browser.setIcon(glyph("globe", C["faint"], 14))
        elif self.api.running():
            self.chip_browser.setText(_('Navegador: pronto (:{port})').format(port=port))
            self.chip_browser.setIcon(glyph("globe", C["accent_hi"], 14))
        else:
            self.chip_browser.setText(_("Navegador: porta ocupada"))
            self.chip_browser.setToolTip(_('Não foi possível abrir a porta {port}: {error}').format(port=port, error=self.api.error))
            self.chip_browser.setIcon(glyph("error", C["accent_hi"], 14))

    # ====================================================== navegador / args
    def _on_api(self, payload):
        if payload.get("show"):
            self.show_window()
            return
        urls = payload.get("urls") or []
        opts = {k: payload[k] for k in ("referer", "cookies", "user_agent", "title") if payload.get(k)}
        if payload.get("kind") in ("hls", "media"):
            opts["kind"] = payload["kind"]
        name = payload.get("filename") or None
        if self.st.get("confirm_browser_links") and not payload.get("silent"):
            self.show_window()
            QApplication.alert(self)
            self.open_add_dialog(urls, opts, name if len(urls) == 1 else None)
        else:
            for u in urls:
                self.m.add(u, None, name if len(urls) == 1 else None, dict(opts), True)
            self._notify(APP_NAME, _('{len} download(s) recebidos do navegador').format(len=len(urls)), self.show_window)
            self._tick()

    def handle_args(self, args):
        urls = [a for a in args if looks_like_url(a)]
        torrents = [a for a in args if a.lower().endswith(".torrent") and os.path.isfile(a)]
        if "--tray" not in args or urls or torrents:
            self.show_window()
        if urls or torrents:
            self.open_add_dialog(urls or None, torrent_files=torrents or None)

    # ======================================================= área de transf.
    def _on_clipboard(self):
        if not self.st.get("clipboard_monitor"):
            return
        text = QApplication.clipboard().text() or ""
        if not text or text == self._own_clip or text == self._last_clip or len(text) > 20000:
            self._last_clip = text
            return
        self._last_clip = text
        urls = [u for u in extract_urls(text) if is_downloadable_url(u) and not self.m.find_duplicate(u)]
        if not urls:
            return
        first = _("link magnet") if urls[0].lower().startswith("magnet:") else filename_from_url(urls[0])
        label = first if len(urls) == 1 else _('{first} e mais {len}').format(first=first, len=len(urls) - 1)
        action = (lambda u=urls: (self.show_window(), self.open_add_dialog(u)))
        if self.isActiveWindow():
            self.banner_show("link", _('Link copiado: {label}').format(label=label), _("Baixar"), action)
        else:
            self._notify(_("Link copiado — clique para baixar"), label, action)

    def banner_show(self, icon, text, button, action, timeout=12000):
        self.banner_icon.setPixmap(glyph(icon, C["accent_hi"], 16).pixmap(16, 16))
        self.banner_text.setText(text)
        self.banner_btn.setVisible(bool(button))
        if button:
            self.banner_btn.setText(button)
        self._banner_action = action
        self.banner.show()
        self._banner_timer.start(timeout)

    def _banner_clicked(self):
        self.banner.hide()
        if self._banner_action:
            act, self._banner_action = self._banner_action, None
            act()

    # ======================================================== arrastar/soltar
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or md.hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        urls, torrents = [], []
        for u in md.urls():
            if u.isLocalFile():
                p = u.toLocalFile()
                if p.lower().endswith(".torrent"):
                    torrents.append(p)
                elif p.lower().endswith((".txt", ".html", ".htm")):
                    try:
                        with open(p, encoding="utf-8", errors="replace") as fh:
                            urls += extract_urls(fh.read())
                    except OSError:
                        pass
            else:
                urls.append(u.toString())
        if not urls and md.hasText():
            urls = extract_urls(md.text())
        urls = [u for u in dict.fromkeys(urls) if looks_like_url(u)]
        if urls or torrents:
            e.acceptProposedAction()
            self.open_add_dialog(urls or None, torrent_files=torrents or None)

    # ============================================================= janela
    def show_window(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized() and reason == QSystemTrayIcon.ActivationReason.Trigger:
                self.hide()
            else:
                self.show_window()

    def _tray_message_clicked(self):
        act, self._tray_action = self._tray_action, None
        if act:
            act()
        else:
            self.show_window()

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))
        self._state_sig = None          # recalcula os contadores ao voltar
        QTimer.singleShot(0, self._tick)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(1500, trim_memory)

    def closeEvent(self, e):
        if (not self._quitting and self.st.get("close_to_tray") and self.tray.isVisible()):
            e.ignore()
            self._save_state()
            self.hide()
            QTimer.singleShot(1500, trim_memory)
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(APP_NAME, _("Continuo rodando aqui na bandeja. Clique com o botão direito "
                                                "para sair."), app_icon(), 4000)
            return
        e.accept()
        self.quit_app()

    def quit_app(self):
        if self._quitting and self._shutdown_done:
            return
        self._quitting = True
        self._save_state()
        self._final_shutdown()
        self.tray.hide()
        QApplication.quit()

    def _final_shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self.timer.stop()
        self.api.stop()
        self.remote.stop()
        keep_awake(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.m.shutdown()
        finally:
            QApplication.restoreOverrideCursor()
