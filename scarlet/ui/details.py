"""Painel inferior: cartão de detalhes com pré-visualização, mapa de seções, gráfico, arquivos do torrent e log."""
import html
import os
import time

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..engine.task import COMPLETED, ERROR, ACTIVE_STATES
from ..util import format_size, format_speed, format_eta, reveal_in_folder
from .model import status_text, display_total
from .theme import C, glyph, category_icon
from .thumbs import is_playable
from ..engine.media_task import quality_label
from ..i18n import _
from .widgets import SegmentBar, SpeedGraph


def _ts(t):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else "—"


def _short(url, n=95):
    return url if len(url) <= n else url[: n - 30] + "…" + url[-28:]


class _Preview(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(256, 144)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:{C['panel2']}; border:1px solid {C['border']}; border-radius:8px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class DetailsPanel(QTabWidget):
    action = Signal(str)          # play | open | folder | copy | zip | move | play_all

    TECH = [("size", "Tamanho"), ("done", "Baixado"), ("speed", "Velocidade"), ("eta", "Tempo restante"),
            ("conns", "Conexões"), ("resume", "Retomável"), ("type", "Tipo"), ("extra", "Detalhes"),
            ("added", "Adicionado"), ("finished", "Concluído"), ("check", "Checksum")]

    def __init__(self, manager, thumbs=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Details")
        self.m = manager
        self.thumbs = thumbs
        self.task = None
        self.selection = []
        self._log_len = -1
        self._files_key = None
        self._preview_key = None

        # ------------------------------------------------ Geral
        self.gen_stack = QStackedWidget()
        # 0: nada selecionado
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setContentsMargins(24, 18, 24, 18)
        self.empty_title = QLabel(_("Selecione um download para ver os detalhes"))
        self.empty_title.setObjectName("H2")
        self.empty_stats = QLabel("")
        self.empty_stats.setObjectName("Muted")
        el.addWidget(self.empty_title)
        el.addWidget(self.empty_stats)
        el.addStretch(1)
        self.gen_stack.addWidget(empty)

        # 1: um download
        card = QWidget()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 10)
        cl.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(16)
        self.preview = _Preview()
        self.preview.clicked.connect(self._preview_clicked)
        top.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(5)
        self.c_title = QLabel("")
        self.c_title.setObjectName("H2")
        self.c_title.setWordWrap(True)
        self.c_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.c_status = QLabel("")
        self.c_media = QLabel("")
        self.c_media.setObjectName("Muted")
        self.c_links = QLabel("")
        self.c_links.setTextFormat(Qt.TextFormat.RichText)
        self.c_links.setWordWrap(True)
        self.c_links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.c_links.linkActivated.connect(self._link)
        brow = QHBoxLayout()
        brow.setSpacing(6)
        self.b_play = self._button("play", _("Reproduzir"), "play", primary=True)
        self.b_open = self._button("open", _("Abrir"), "open")
        self.b_folder = self._button("folder", _("Abrir pasta"), "folder")
        self.b_copy = self._button("copy", _("Copiar link"), "copy")
        for b in (self.b_play, self.b_open, self.b_folder, self.b_copy):
            brow.addWidget(b)
        brow.addStretch(1)
        for w in (self.c_title, self.c_status, self.c_media, self.c_links):
            col.addWidget(w)
        col.addStretch(1)
        col.addLayout(brow)
        top.addLayout(col, 1)
        cl.addLayout(top)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C['border']}")
        cl.addWidget(sep)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        self.values = {}
        for i, (key, label) in enumerate(self.TECH):
            row, colx = i % 4, (i // 4) * 2
            k = QLabel(_(label))
            k.setObjectName("Faint")
            v = QLabel("—")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setObjectName("Muted")
            grid.addWidget(k, row, colx)
            grid.addWidget(v, row, colx + 1)
            self.values[key] = v
        for c in (1, 3, 5):
            grid.setColumnStretch(c, 1)
        cl.addLayout(grid)
        cl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(card)
        self.gen_stack.addWidget(scroll)

        # 2: vários
        multi = QWidget()
        ml = QVBoxLayout(multi)
        ml.setContentsMargins(24, 18, 24, 18)
        self.m_title = QLabel("")
        self.m_title.setObjectName("H2")
        self.m_info = QLabel("")
        self.m_info.setObjectName("Muted")
        mrow = QHBoxLayout()
        self.mb_play = self._button("play", _("Reproduzir todos"), "play_all", primary=True)
        self.mb_zip = self._button("archive", _("Compactar em ZIP"), "zip")
        self.mb_move = self._button("folder", _("Mover para pasta…"), "move")
        self.mb_copy = self._button("copy", _("Copiar links"), "copy")
        for b in (self.mb_play, self.mb_zip, self.mb_move, self.mb_copy):
            mrow.addWidget(b)
        mrow.addStretch(1)
        ml.addWidget(self.m_title)
        ml.addWidget(self.m_info)
        ml.addSpacing(8)
        ml.addLayout(mrow)
        ml.addStretch(1)
        self.gen_stack.addWidget(multi)
        self.addTab(self.gen_stack, _("Geral"))

        # ------------------------------------------------ Mapa
        mp = QWidget()
        mpl = QVBoxLayout(mp)
        mpl.setContentsMargins(16, 12, 16, 12)
        self.map_title = QLabel("")
        self.map_title.setObjectName("Muted")
        self.bar = SegmentBar()
        legend = QHBoxLayout()
        for color, text in ((C["accent"], _("baixado")), (C["live"], _("conexão ativa")), (C["map_bg"], _("falta"))):
            sw = QLabel()
            sw.setFixedSize(12, 12)
            sw.setStyleSheet(f"background:{color}; border-radius:3px; border:1px solid {C['border']}")
            legend.addWidget(sw)
            lab = QLabel(text)
            lab.setObjectName("Muted")
            legend.addWidget(lab)
            legend.addSpacing(10)
        legend.addStretch(1)
        self.seg_table = QTableWidget(0, 6)
        self.seg_table.setHorizontalHeaderLabels(["#", _("Início"), _("Fim"), _("Baixado"), "%", _("Conexão")])
        self.seg_table.verticalHeader().setVisible(False)
        self.seg_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.seg_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.seg_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.seg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.seg_table.verticalHeader().setDefaultSectionSize(26)
        mpl.addWidget(self.map_title)
        mpl.addWidget(self.bar)
        mpl.addLayout(legend)
        mpl.addWidget(self.seg_table, 1)
        self.addTab(mp, _("Mapa de seções"))

        # ------------------------------------------------ Velocidade
        self.graph = SpeedGraph()
        gw = QWidget()
        gl = QVBoxLayout(gw)
        gl.setContentsMargins(10, 10, 10, 10)
        gl.addWidget(self.graph)
        self.addTab(gw, _("Velocidade"))

        # ------------------------------------------------ Arquivos (torrent)
        self.files = QTreeWidget()
        self.files.setHeaderLabels([_("Arquivo"), _("Tamanho"), _("Progresso")])
        self.files.setRootIsDecorated(False)
        self.files.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files.itemChanged.connect(self._file_toggled)
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(10, 10, 10, 10)
        tip = QLabel(_("Desmarque os arquivos que não quer baixar."))
        tip.setObjectName("Muted")
        fl.addWidget(tip)
        fl.addWidget(self.files)
        self.files_index = self.addTab(fw, _("Arquivos"))

        # ------------------------------------------------ Log
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas, 'Cascadia Mono', Menlo, 'DejaVu Sans Mono', monospace; font-size: 9pt;")
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.addWidget(self.log)
        self.log_index = self.addTab(lw, _("Log"))

        self.currentChanged.connect(lambda _: self.refresh(force=True))
        self.setTabVisible(self.files_index, False)
        if self.thumbs is not None:
            self.thumbs.ready.connect(self._thumb_ready)

    def _button(self, icon, text, act, primary=False):
        b = QPushButton(glyph(icon, C["on_accent"] if primary else C["muted"], 14), " " + text)
        if primary:
            b.setObjectName("Primary")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: self.action.emit(act))
        return b

    # ------------------------------------------------ seleção
    def set_selection(self, tasks):
        self.selection = list(tasks)
        task = tasks[0] if len(tasks) == 1 else None
        if task is not self.task:
            self.task = task
            self._log_len = -1
            self._files_key = None
            self._preview_key = None
        self.setTabVisible(self.files_index, bool(task and task.kind == "torrent"))
        self.refresh(force=True)

    def set_task(self, task):
        self.set_selection([task] if task else [])

    def _thumb_ready(self, task_id):
        if self.task is not None and self.task.id == task_id:
            self._preview_key = None
            self.refresh(force=True)

    def _preview_clicked(self):
        t = self.task
        if t is None:
            return
        if t.status == COMPLETED and is_playable(t):
            self.action.emit("play")
        elif t.status == COMPLETED:
            self.action.emit("open")

    def _link(self, href):
        if href.startswith("folder:"):
            reveal_in_folder(href[7:])
        else:
            QDesktopServices.openUrl(QUrl(href))

    # ------------------------------------------------ atualização
    def refresh(self, force=False):
        t = self.task
        if t is not None and t not in self.m.tasks:
            # a tarefa pode ter sido trocada (conversão para HLS) ou removida
            t = self.task = next((x for x in self.m.tasks if x.id == t.id), None)
            self.selection = [t] if t else []
        self.selection = [x for x in self.selection if x in self.m.tasks]
        if not self.isVisible() and not force:
            return
        idx = self.currentIndex()
        if idx == 0:
            if len(self.selection) > 1:
                self._multi()
            elif t is None:
                self._empty()
            else:
                self._card(t)
            return
        if t is None:
            self.bar.set_ranges(0, [])
            self.seg_table.setRowCount(0)
            self.map_title.setText(_("Selecione um download"))
            self.graph.set_series([], self._global_history(), _("total (cinza)"))
            self.log.setPlainText("")
            return
        if idx == 1:
            self._map(t)
        elif idx == 2:
            self.graph.set_series(t.speed_history, self._global_history(),
                                  _('{name}: {format_speed} · total (cinza)').format(name=t.name[:40], format_speed=format_speed(t.speed) or '0'))
        elif idx == self.files_index:
            self._files(t)
        elif idx == self.log_index:
            if len(t.log) != self._log_len or force:
                self._log_len = len(t.log)
                lines = [f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {msg}" for ts, msg in t.log]
                self.log.setPlainText("\n".join(lines))
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _global_history(self):
        hist = [list(x.speed_history) for x in self.m.tasks if x.speed_history]
        if not hist:
            return []
        n = max(len(h) for h in hist)
        out = [0.0] * n
        for h in hist:
            off = n - len(h)
            for i, v in enumerate(h):
                out[off + i] += v
        return out

    def _empty(self):
        self.gen_stack.setCurrentIndex(0)
        tasks = list(self.m.tasks)
        done = [x for x in tasks if x.status == COMPLETED]
        act = sum(1 for x in tasks if x.status in ACTIVE_STATES)
        total = sum(max(0, x.total) for x in done)
        self.empty_stats.setText(
            _('{len} downloads na lista · {len2} concluídos ({format_size}) · {act} ativos · velocidade agora {format_speed}').format(len=len(tasks), len2=len(done), format_size=format_size(total), act=act, format_speed=format_speed(self.m.total_speed()) or '0 B/s'))

    def _multi(self):
        self.gen_stack.setCurrentIndex(2)
        sel = self.selection
        done = [x for x in sel if x.status == COMPLETED]
        size = sum(max(0, display_total(x)[0]) for x in sel)
        self.m_title.setText(_('{len} downloads selecionados').format(len=len(sel)))
        self.m_info.setText(_('Tamanho total {format_size} · {len} concluídos · {sum} baixando').format(format_size=format_size(size), len=len(done), sum=sum(1 for x in sel if x.status in ACTIVE_STATES)))
        playable = [x for x in done if is_playable(x) and os.path.exists(x.path)]
        self.mb_play.setVisible(bool(playable))
        self.mb_play.setText(_(' Reproduzir {len}').format(len=len(playable)) if playable else _(" Reproduzir"))
        exists = [x for x in done if os.path.exists(x.path) or x.kind == "torrent"]
        self.mb_zip.setEnabled(bool(exists))
        self.mb_move.setEnabled(bool(exists))

    def _card(self, t):
        self.gen_stack.setCurrentIndex(1)
        exists = t.status == COMPLETED and os.path.exists(t.path)
        # pré-visualização
        key = (t.id, t.status, exists)
        if key != self._preview_key:
            pm = self.thumbs.pixmap(t) if self.thumbs else None
            if pm is not None:
                w, h = self.preview.width(), self.preview.height()
                sc = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
                self.preview.setPixmap(sc.copy((sc.width() - w) // 2, (sc.height() - h) // 2, w, h))
                self._preview_key = key
            else:
                cat = "stream" if t.kind == "hls" else t.category
                self.preview.setPixmap(category_icon(cat).pixmap(64, 64))
                if not (self.thumbs and self.thumbs.wants(t)):
                    self._preview_key = key
            self.preview.setToolTip(_("Clique para reproduzir") if exists and is_playable(t)
                                    else _("Clique para abrir") if exists else "")
        self.c_title.setText(t.name)
        st = status_text(t)
        p = t.progress()
        if t.status not in (COMPLETED,) and p is not None:
            st += f" · {p * 100:.1f}%".replace(".", ",")
        if t.status in ACTIVE_STATES and t.speed:
            st += f" · {format_speed(t.speed)}"
            eta = format_eta(t.eta())
            if eta:
                st += _(' · faltam {eta}').format(eta=eta)
        color = C["error"] if t.status == ERROR or (t.status == COMPLETED and t.missing) else C["text"]
        self.c_status.setStyleSheet(f"color:{color};")
        self.c_status.setText(st)
        info = self.thumbs.describe(self.thumbs.info(t)) if (self.thumbs and exists) else ""
        if t.kind == "media" and not info:
            info = quality_label(t.options)
        self.c_media.setText(info)
        self.c_media.setVisible(bool(info))
        links = []
        a = f"color:{C['accent_hi']}; text-decoration:none;"
        folder_target = t.path if exists else t.save_dir
        links.append(f"{glyph_html('📁')} Pasta: <a style='{a}' href='folder:{html.escape(folder_target)}'>"
                     f"{html.escape(t.save_dir)}</a>")
        page = t.options.get("referer") or (t.url if t.kind == "media" else "")
        if page and page.startswith("http"):
            links.append(f"{glyph_html('🌐')} Página: <a style='{a}' href='{html.escape(page)}'>"
                         f"{html.escape(_short(page))}</a>")
        file_url = getattr(t, "final_url", "") or (t.url if t.kind != "media" else "")
        if file_url and file_url.startswith(("http", "ftp")):
            links.append(f"{glyph_html('🔗')} Arquivo: <a style='{a}' href='{html.escape(file_url)}'>"
                         f"{html.escape(_short(file_url))}</a>")
        elif t.url.startswith("magnet:"):
            links.append(_('{glyph_html} Magnet: {escape}').format(glyph_html=glyph_html('🧲'), escape=html.escape(_short(t.url, 80))))
        if t.status == ERROR and t.error:
            links.append(f"<span style='color:{C['accent_hi']}'>⚠ {html.escape(t.error)}</span>")
        self.c_links.setText("<br>".join(links))
        self.b_play.setVisible(exists and is_playable(t))
        self.b_open.setEnabled(exists or (t.kind == "torrent" and t.status == COMPLETED))
        self.b_copy.setEnabled(bool(t.url))
        self._tech(t)

    def _tech(self, t):
        v = self.values
        v["size"].setText(display_total(t)[1])
        p = t.progress()
        pct = f" ({p * 100:.1f}%)".replace(".", ",") if p is not None else ""
        if t.kind == "convert":       # progresso é em tempo de vídeo, não em bytes
            v["done"].setText(pct.strip(" ()") or "—")
        else:
            v["done"].setText(format_size(t.done) + pct)
        if t.kind == "torrent":
            v["speed"].setText(f"↓ {format_speed(t.speed) or '0'}   ↑ {format_speed(t.up_speed) or '0'}")
            v["conns"].setText(_('{peers} peers ({seeds} seeds)').format(peers=t.peers, seeds=t.seeds))
        else:
            v["speed"].setText(format_speed(t.speed) or "—")
            v["conns"].setText(str(t.connections_active))
        v["eta"].setText(format_eta(t.eta()) or "—")
        if t.kind == "http":
            v["resume"].setText({True: _("Sim"), False: _("Não")}.get(t.resumable, "?"))
            v["type"].setText(t.content_type or "—")
            v["extra"].setText(_('{len} seções').format(len=len(t.segments)))
            cs = t.options.get("checksum") or {}
            if cs.get("value"):
                st = {True: _("confere ✓"), False: _("NÃO confere"), None: "aguardando"}[t.verified]
                v["check"].setText(f"{cs.get('algo', 'sha256').upper()} {st}")
            else:
                v["check"].setText("—")
        elif t.kind == "hls":
            v["resume"].setText(_("Sim (por pedaço)"))
            v["type"].setText(_("Stream HLS → MP4"))
            v["extra"].setText(f"{len(t.done_set)}/{len(t.items)} pedaços · {t.variant_info or 'automática'}")
            v["check"].setText("—")
        elif t.kind == "convert":
            v["resume"].setText(_("Não (recomeça do zero)"))
            v["type"].setText(_("Conversão") + " · " + os.path.basename(t.source))
            v["extra"].setText(t.stage or "—")
            v["check"].setText("—")
        elif t.kind == "media":
            v["resume"].setText(_("Sim"))
            v["type"].setText(_("Vídeo/música de site") + " · " + quality_label(t.options))
            v["extra"].setText(t.stage or "—")
            v["check"].setText("—")
        else:
            v["resume"].setText(_("Sim"))
            v["type"].setText(_("Torrent"))
            v["extra"].setText(f"enviado {format_size(t.uploaded)}")
            v["check"].setText(_("verificado por peça"))
        v["added"].setText(_ts(t.added))
        v["finished"].setText(_ts(t.finished))

    # ------------------------------------------------ mapa / arquivos
    def _map(self, t):
        if t.kind == "http":
            with t.lock:
                segs = [(s.start, s.end, s.pos, s.active) for s in t.segments]
            total = t.total if t.total > 0 else max([s[2] for s in segs] + [1])
            self.bar.set_ranges(total, segs)
            act = sum(1 for s in segs if s[3])
            self.map_title.setText(_('{len} seções · {act} conexões ativas · {format_size} de {format_size2}').format(len=len(segs), act=act, format_size=format_size(t.done), format_size2=format_size(t.total)))
            rows = segs[:300]
            self.seg_table.setRowCount(len(rows))
            for i, (a, b, pos, active) in enumerate(rows):
                size = (b - a) if b >= 0 else 0
                got = pos - a
                pc = f"{got / size * 100:.0f}%" if size > 0 else "—"
                vals = [str(i + 1), format_size(a), format_size(b) if b >= 0 else "?", format_size(got), pc,
                        "ativa" if active else (_("concluída") if b >= 0 and pos >= b else "aguardando")]
                for j, val in enumerate(vals):
                    it = self.seg_table.item(i, j)
                    if it is None:
                        it = QTableWidgetItem()
                        self.seg_table.setItem(i, j, it)
                    it.setText(val)
                    if j == 5:
                        it.setForeground(QColor(C["accent_hi"] if active else C["muted"]))
        elif t.kind == "hls":
            pieces = [i in t.done_set for i in range(len(t.items))]
            self.bar.set_pieces(pieces)
            self.map_title.setText(f"{sum(pieces)}/{len(pieces)} pedaços do stream · {t.connections_active} conexões")
            self.seg_table.setRowCount(0)
        elif t.kind == "media":
            p = t.progress() or 0
            total = 1000
            self.bar.set_ranges(total, [(0, total, int(total * p), t.status in ACTIVE_STATES)])
            self.map_title.setText(_("Vídeo de site: {p}% do arquivo atual").format(p=f"{p * 100:.0f}"))
            self.seg_table.setRowCount(0)
        else:
            pieces = t.pieces()
            self.bar.set_pieces(pieces)
            self.map_title.setText(f"{sum(pieces)}/{len(pieces)} peças · {t.peers} peers" if pieces
                                   else _("Aguardando metadados do torrent"))
            self.seg_table.setRowCount(0)

    def _files(self, t):
        key = (t.id, len(t.files))
        self.files.blockSignals(True)
        if key != self._files_key:
            self._files_key = key
            self.files.clear()
            pri = t.priorities or [4] * len(t.files)
            for i, (path, size) in enumerate(t.files):
                it = QTreeWidgetItem([path, format_size(size), ""])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if (i >= len(pri) or pri[i] > 0) else Qt.CheckState.Unchecked)
                it.setData(0, Qt.ItemDataRole.UserRole, i)
                self.files.addTopLevelItem(it)
        prog = t.file_progress
        for i in range(self.files.topLevelItemCount()):
            it = self.files.topLevelItem(i)
            size = t.files[i][1] if i < len(t.files) else 0
            if i < len(prog) and size:
                it.setText(2, f"{prog[i] / size * 100:.1f}%".replace(".", ","))
        self.files.blockSignals(False)

    def _file_toggled(self, item, col):
        if col != 0 or self.task is None or self.task.kind != "torrent":
            return
        i = item.data(0, Qt.ItemDataRole.UserRole)
        self.task.set_file_wanted(i, item.checkState(0) == Qt.CheckState.Checked)


def glyph_html(emoji):
    return f"<span style='font-family:\"Segoe UI Emoji\", \"Apple Color Emoji\", \"Noto Color Emoji\"'>{emoji}</span>"
