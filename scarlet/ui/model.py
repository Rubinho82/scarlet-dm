"""Modelo da tabela de downloads, filtro/ordenação e o desenho da barra de progresso."""
import os
import time

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from ..engine.task import (STATUS_LABELS, ACTIVE_STATES, QUEUED, PAUSED, COMPLETED, ERROR, DOWNLOADING,
                           SEEDING, PROCESSING, STARTING)
from ..engine.media_task import quality_label
from ..util import format_size, format_speed, format_eta
from ..i18n import _
from .theme import C, category_icon

COLS = ["Nome", "Estado", "Progresso", "Velocidade", "Restante", "Tamanho", "Adicionado"]
COL_NAME, COL_STATUS, COL_PROGRESS, COL_SPEED, COL_ETA, COL_SIZE, COL_ADDED = range(7)
TaskRole = Qt.ItemDataRole.UserRole + 1
SortRole = Qt.ItemDataRole.UserRole + 2


def status_text(t):
    if t.status == ERROR:
        return _("Erro: ") + (t.error or "falha")
    if t.status == COMPLETED and t.missing:
        return _("Arquivo ausente")
    if t.kind == "torrent" and getattr(t, "state_text", "") and t.status not in (PAUSED, QUEUED, COMPLETED):
        txt = t.state_text
        if t.status == DOWNLOADING or not txt:
            txt = _(STATUS_LABELS[t.status])
        return _('{txt} · {peers} peers').format(txt=txt, peers=t.peers) if t.status in (DOWNLOADING, SEEDING) else txt
    base = _(STATUS_LABELS.get(t.status, t.status))
    if t.status == DOWNLOADING:
        n = t.connections_active
        if n > 1:
            return _('{base} · {n} conexões').format(base=base, n=n)
    if t.status == PROCESSING and t.kind == "http" and t.options.get("checksum", {}).get("value"):
        return _("Verificando checksum…")
    if t.kind == "media" and t.status == PROCESSING and getattr(t, "stage", ""):
        return t.stage + "…"
    if t.kind == "media" and t.status == DOWNLOADING:
        return f"{_(STATUS_LABELS[DOWNLOADING])} · {quality_label(t.options)}"
    return base


def display_total(t):
    if t.kind == "hls" and t.status != COMPLETED:
        est = t.est_total()
        return est, ("~" + format_size(est)) if est > 0 else "—"
    if t.kind == "media" and t.status != COMPLETED:
        est = t._base_done + t._cur_total
        return est, ("~" + format_size(est)) if est > 0 else "—"
    return t.total, format_size(t.total)


def added_text(ts):
    lt = time.localtime(ts)
    now = time.localtime()
    if lt.tm_year == now.tm_year and lt.tm_yday == now.tm_yday:
        return time.strftime("%H:%M", lt)
    return time.strftime("%d/%m/%Y", lt)


class DownloadsModel(QAbstractTableModel):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.m = manager
        self.thumbs = None
        self._tasks = []
        self._ids = []

    def task(self, row):
        return self._tasks[row]

    @staticmethod
    def _sig(t):
        """O que aparece na linha; se não mudou, a linha não é redesenhada (economiza CPU em listas grandes)."""
        p = t.progress()
        return (t.status, t.name, t.error, t.missing, int(t.speed) >> 10, None if p is None else int(p * 1000),
                t.connections_active, t.total, getattr(t, "stage", ""))

    def refresh(self):
        """Atualiza só o que mudou. Retorna True se a lista mudou de estrutura (linhas entraram/saíram)."""
        tasks = list(self.m.tasks)
        ids = [t.id for t in tasks]
        if ids != self._ids:
            self.beginResetModel()
            self._tasks, self._ids = tasks, ids
            self._sigs = [self._sig(t) for t in tasks]
            self.endResetModel()
            return True
        self._tasks = tasks
        sigs = getattr(self, "_sigs", None)
        if sigs is None or len(sigs) != len(tasks):
            sigs = self._sigs = [None] * len(tasks)
        last = len(COLS) - 1
        start = None
        for i, t in enumerate(tasks):
            sg = self._sig(t)
            changed = sg != sigs[i] or (t.status in ACTIVE_STATES and t.progress() is None)
            if changed:
                sigs[i] = sg
                if start is None:
                    start = i
            elif start is not None:
                self.dataChanged.emit(self.index(start, 0), self.index(i - 1, last))
                start = None
        if start is not None:
            self.dataChanged.emit(self.index(start, 0), self.index(len(tasks) - 1, last))
        return False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._tasks)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _(COLS[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        t = self._tasks[index.row()]
        c = index.column()
        if role == TaskRole:
            return t
        if role == Qt.ItemDataRole.DisplayRole:
            if c == COL_NAME:
                return t.name
            if c == COL_STATUS:
                return status_text(t)
            if c == COL_SPEED:
                return format_speed(t.speed) if t.status in ACTIVE_STATES or t.status == SEEDING else ""
            if c == COL_ETA:
                return format_eta(t.eta()) if t.status == DOWNLOADING else ""
            if c == COL_SIZE:
                return display_total(t)[1]
            if c == COL_ADDED:
                return added_text(t.added)
            return None
        if role == Qt.ItemDataRole.DecorationRole and c == COL_NAME:
            if self.thumbs is not None:
                ic = self.thumbs.icon(t)
                if ic is not None:
                    return ic
            return category_icon("stream" if t.kind == "hls" else t.category)
        if role == Qt.ItemDataRole.ForegroundRole:
            if c == COL_STATUS:
                if t.status == ERROR or (t.status == COMPLETED and t.missing):
                    return QColor(C["accent_hi"])
                if t.status in (DOWNLOADING, STARTING, PROCESSING, SEEDING):
                    return QColor(C["text"])
                return QColor(C["muted"])
            if c in (COL_SPEED, COL_ETA, COL_SIZE, COL_ADDED):
                return QColor(C["muted"])
            if c == COL_NAME and t.status == COMPLETED and t.missing:
                return QColor(C["faint"])
        if role == Qt.ItemDataRole.ToolTipRole:
            if c == COL_NAME:
                return f"{t.path}\n{t.url or getattr(t, 'torrent_file', '')}"
            if c == COL_STATUS and t.error:
                return t.error
        if role == Qt.ItemDataRole.TextAlignmentRole and c in (COL_SPEED, COL_ETA, COL_SIZE):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == SortRole:
            if c == COL_NAME:
                return t.name.lower()
            if c == COL_STATUS:
                return status_text(t)
            if c == COL_PROGRESS:
                p = t.progress()
                return -1 if p is None else p
            if c == COL_SPEED:
                return t.speed
            if c == COL_ETA:
                e = t.eta()
                return 1e12 if e is None else e
            if c == COL_SIZE:
                return display_total(t)[0]
            if c == COL_ADDED:
                return t.added
        return None


FILTERS = [
    ("all", "Todos"), ("active", "Ativos"), ("completed", "Concluídos"), ("paused", "Pausados"),
    ("error", "Com erro"), ("missing", "Arquivos ausentes"),
    ("video", "Vídeo"), ("audio", "Música"), ("document", "Documentos"), ("archive", "Compactados"),
    ("program", "Programas"), ("image", "Imagens"), ("torrent", "Torrent"),
]
STATUS_FILTERS = {"all", "active", "completed", "paused", "error", "missing"}


def matches(t, key):
    if key == "all":
        return True
    if key == "active":
        return t.status in ACTIVE_STATES or t.status in (QUEUED, SEEDING)
    if key == "completed":
        return t.status == COMPLETED
    if key == "paused":
        return t.status == PAUSED
    if key == "error":
        return t.status == ERROR
    if key == "missing":
        return t.status == COMPLETED and t.missing
    cat = "video" if t.kind == "hls" else t.category
    return cat == key


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = "all"
        self.text = ""
        self.setSortRole(SortRole)
        self.setDynamicSortFilter(True)

    def set_key(self, key):
        self.key = key
        self.invalidateFilter()

    def set_text(self, text):
        self.text = (text or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        t = self.sourceModel().task(row)
        if not matches(t, self.key):
            return False
        if self.text:
            return self.text in t.name.lower() or self.text in (t.url or "").lower()
        return True


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        t = index.data(TaskRole)
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        if t is None:
            return
        p = t.progress()
        r = QRectF(option.rect).adjusted(8, option.rect.height() / 2 - 4, -8, -(option.rect.height() / 2 - 4))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#232329"))
        painter.drawRoundedRect(r, 4, 4)
        if p is not None and p > 0:
            fill = QRectF(r)
            fill.setWidth(max(4.0, r.width() * min(1.0, p)))
            if t.status == COMPLETED:
                color = QColor(C["accent_lo"])
                painter.setBrush(color)
            elif t.status in (PAUSED, QUEUED):
                painter.setBrush(QColor("#5a1a20"))
            elif t.status == ERROR:
                painter.setBrush(QColor("#6e2a10"))
            else:
                g = QLinearGradient(fill.topLeft(), fill.topRight())
                g.setColorAt(0, QColor(C["accent_lo"]))
                g.setColorAt(1, QColor(C["accent_hi"]))
                painter.setBrush(g)
            painter.drawRoundedRect(fill, 4, 4)
        elif p is None and t.status in (DOWNLOADING, STARTING):
            # tamanho desconhecido: faixa animada indo e voltando
            phase = (time.time() * 0.8) % 2
            x = phase if phase <= 1 else 2 - phase
            w = r.width() * 0.25
            painter.setBrush(QColor(C["accent"]))
            painter.drawRoundedRect(QRectF(r.left() + (r.width() - w) * x, r.top(), w, r.height()), 4, 4)
        txt = ""
        if t.status == COMPLETED:
            txt = ""
        elif p is not None:
            txt = f"{p * 100:.1f}%".replace(".", ",")
        if txt:
            painter.setPen(QColor(C["text"]))
            f = QFont(option.font)
            f.setPointSizeF(8.5)
            painter.setFont(f)
            tr = QRectF(option.rect).adjusted(8, 0, -8, 0)
            painter.drawText(tr, Qt.AlignmentFlag.AlignCenter, txt)
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setWidth(140)
        return s


def task_at(view, proxy_index):
    if not proxy_index.isValid():
        return None
    return proxy_index.data(TaskRole)


def file_exists(t):
    return os.path.exists(t.path)
