"""Widgets próprios: mapa de seções, gráfico de velocidade e barra de filtros."""
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from ..util import format_speed
from ..i18n import _
from .theme import C


class SegmentBar(QWidget):
    """Desenha o arquivo inteiro: o que já baixou, onde cada conexão está e o que falta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.total = 0
        self.ranges = []     # (start, end, pos, active)
        self.pieces = []     # bools (HLS/torrent)

    def set_ranges(self, total, ranges):
        self.total, self.ranges, self.pieces = total, ranges, []
        self.update()

    def set_pieces(self, pieces):
        self.total, self.ranges, self.pieces = 0, [], pieces
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 4, -1, -4)
        path = QPainterPath()
        path.addRoundedRect(r, 5, 5)
        p.setClipPath(path)
        p.fillRect(r, QColor("#1e1e24"))
        w = r.width()
        if self.ranges and self.total > 0:
            for start, end, pos, active in self.ranges:
                x0 = r.left() + w * start / self.total
                x1 = r.left() + w * max(start, pos) / self.total
                if x1 > x0:
                    g = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
                    g.setColorAt(0, QColor(C["accent_hi"] if active else C["accent"]))
                    g.setColorAt(1, QColor(C["accent_lo"]))
                    p.fillRect(QRectF(x0, r.top(), max(1.0, x1 - x0), r.height()), g)
                if active and (end < 0 or pos < end):
                    p.fillRect(QRectF(x1 - 1, r.top(), 2, r.height()), QColor("#ffffff"))
                p.fillRect(QRectF(x0, r.top(), 1, r.height()), QColor(0, 0, 0, 160))
        elif self.pieces:
            n = len(self.pieces)
            cols = max(1, int(w))
            for i in range(cols):
                a = int(i * n / cols)
                b = max(a + 1, int((i + 1) * n / cols))
                chunk = self.pieces[a:b]
                frac = sum(1 for x in chunk if x) / len(chunk)
                if frac > 0:
                    c = QColor(C["accent"])
                    c.setAlphaF(0.35 + 0.65 * frac)
                    p.fillRect(QRectF(r.left() + i, r.top(), 1.2, r.height()), c)
        p.setClipping(False)
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 5, 5)
        p.end()


class SpeedGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.series = []
        self.series2 = []
        self.label = ""

    def set_series(self, values, values2=None, label=""):
        self.series = list(values)
        self.series2 = list(values2 or [])
        self.label = label
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(52, 10, -10, -18)
        p.fillRect(self.rect(), QColor(C["panel"]))
        top = max([64 * 1024.0] + self.series + self.series2)
        nice = 64 * 1024.0
        while nice < top:
            nice *= 2
        top = nice
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            p.setPen(QPen(QColor("#202026"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(C["faint"]))
            p.drawText(QRectF(0, y - 8, 48, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       format_speed(top * i / 4) or "0")
        for series, color, fill in ((self.series2, "#6b6b75", False), (self.series, C["accent"], True)):
            if len(series) < 2:
                continue
            n = 120
            pts = []
            start = max(0, len(series) - n)
            vals = series[start:]
            for i, v in enumerate(vals):
                x = r.right() - (len(vals) - 1 - i) * r.width() / (n - 1)
                y = r.bottom() - r.height() * min(1.0, v / top)
                pts.append(QPointF(x, y))
            line = QPainterPath(pts[0])
            for pt in pts[1:]:
                line.lineTo(pt)
            if fill:
                area = QPainterPath(line)
                area.lineTo(QPointF(pts[-1].x(), r.bottom()))
                area.lineTo(QPointF(pts[0].x(), r.bottom()))
                area.closeSubpath()
                g = QLinearGradient(QPointF(0, r.top()), QPointF(0, r.bottom()))
                c1 = QColor(C["accent"])
                c1.setAlpha(110)
                c2 = QColor(C["accent"])
                c2.setAlpha(8)
                g.setColorAt(0, c1)
                g.setColorAt(1, c2)
                p.fillPath(area, g)
            p.setPen(QPen(QColor(color), 2 if fill else 1.2))
            p.drawPath(line)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, _("últimos 60 s"))
        if self.label:
            p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.label)
        p.end()


class FilterBar(QWidget):
    changed = Signal(str)

    def __init__(self, filters, always, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 0)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self.labels = {k: _(v) for k, v in filters}
        self.always = set(always)
        for key, label in filters:
            b = QPushButton(_(label))
            b.setObjectName("Filter")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)

    def select(self, key):
        b = self.buttons.get(key) or self.buttons["all"]
        b.setChecked(True)

    def update_counts(self, counts, current):
        for key, b in self.buttons.items():
            n = counts.get(key, 0)
            b.setText(f"{self.labels[key]} ({n})" if n or key == "all" else self.labels[key])
            b.setVisible(key in self.always or n > 0 or key == current)
