"""Tema (escuro ou claro, cor de destaque à escolha): cores, folha de estilo, ícones vetoriais e ícone do app."""
import os

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

from ..util import app_data_dir

C = {
    "bg": "#0a0a0c",
    "panel": "#111114",
    "panel2": "#16161a",
    "panel3": "#1d1d22",
    "border": "#26262c",
    "row": "#141418",
    "text": "#ededf1",
    "muted": "#8d8d97",
    "faint": "#55555e",
    "accent": "#e3222f",
    "accent_hi": "#ff3d49",
    "accent_lo": "#7d141c",
    "sel": "#3b0f15",
    "warn": "#ff8a3d",
    "ok": "#e3222f",
    # tons que antes estavam fixos no código
    "track": "#2a2a31",        # trilho de slider
    "bar_bg": "#232329",       # fundo da barra de progresso da lista
    "map_bg": "#1e1e24",       # parte que falta no mapa de conexões
    "bar_paused": "#5a1a20",
    "bar_error": "#6e2a10",
    "hover": "#131317",        # linha da lista sob o mouse
    "scroll": "#2b2b32",
    "btn_hover": "#24242a",
    "box_border": "#3c3c45",   # caixinhas de marcar
    "grid": "#202026",         # linhas do gráfico de velocidade
    "series2": "#6b6b75",
    "live": "#ffffff",         # marcador de conexão ativa
    "knob": "#ffffff",
    "on_accent": "#ffffff",    # texto/ícone sobre a cor de destaque
    "error": "#ff3d49",        # erro fica vermelho mesmo com outra cor de destaque
}
DARK = dict(C)
LIGHT = dict(DARK, **{
    "bg": "#f5f5f7", "panel": "#ffffff", "panel2": "#f0f0f3", "panel3": "#e8e8ed", "border": "#d9d9e0",
    "row": "#ececf0", "text": "#1b1b21", "muted": "#5f5f69", "faint": "#a0a0aa", "warn": "#c8570f",
    "track": "#d6d6dd", "bar_bg": "#e3e3e9", "map_bg": "#e3e3e9", "hover": "#f0f0f4", "scroll": "#c6c6cf",
    "btn_hover": "#f1f1f4", "box_border": "#b5b5bf", "error": "#d01f2b", "grid": "#e6e6eb", "series2": "#9a9aa4", "live": "#1b1b21",
})
# cor de destaque: nome -> (cor, rótulo)
ACCENTS = {
    "red": ("#e3222f", "Vermelho"), "blue": ("#2f6fed", "Azul"), "green": ("#1e9e57", "Verde"),
    "purple": ("#8b5cf6", "Roxo"), "orange": ("#f0661a", "Laranja"), "pink": ("#e0457b", "Rosa"),
    "teal": ("#0f9f9c", "Turquesa"),
}
THEME = {"mode": "dark", "accent": "red"}

# Glifos das fontes de ícones do Windows (Segoe Fluent Icons / Segoe MDL2 Assets).
G = {
    "add": "", "play": "", "pause": "", "delete": "", "folder": "",
    "search": "", "menu": "", "settings": "", "link": "", "down": "",
    "up": "", "refresh": "", "copy": "", "close": "", "paste": "",
    "import": "", "save": "", "power": "", "speed": "", "info": "",
    "video": "", "audio": "", "document": "", "archive": "", "program": "",
    "image": "", "torrent": "", "stream": "", "other": "", "check": "",
    "error": "", "clock": "", "globe": "", "calendar": "", "chevron": "",
    "open": "", "top": "", "bottom": "", "edit": "", "chart": "",
}

CATEGORY_COLORS = {
    "video": "#ff4b57", "audio": "#ff6f86", "document": "#c9c9d2", "archive": "#ff9f43",
    "program": "#e3222f", "image": "#ff8fa3", "torrent": "#ff5e57", "other": "#9a9aa5", "stream": "#ff4b57",
}
_RED_CATEGORIES = dict(CATEGORY_COLORS)


def _mix(c1, c2, t):
    """Mistura duas cores "#rrggbb": t=0 dá c1, t=1 dá c2."""
    a, b = QColor(c1), QColor(c2)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def system_is_dark():
    """Tema do sistema (Windows/macOS/GNOME), quando dá para saber; senão, escuro."""
    try:
        from PySide6.QtGui import QGuiApplication
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return False
        if scheme == Qt.ColorScheme.Dark:
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    return True


def is_dark():
    return THEME["mode"] != "light"


def apply_theme(mode="dark", accent="red"):
    """Monta as cores antes de criar as janelas. mode: "dark", "light" ou "system"; accent: chave de ACCENTS ou
    "#rrggbb". O vermelho no tema escuro fica exatamente como sempre foi."""
    if mode == "system":
        mode = "dark" if system_is_dark() else "light"
    mode = "light" if mode == "light" else "dark"
    if isinstance(accent, str) and accent.startswith("#") and QColor(accent).isValid():
        base = QColor(accent).name()
    else:
        accent = accent if accent in ACCENTS else "red"
        base = ACCENTS[accent][0]
    THEME.update(mode=mode, accent=accent)
    pal = dict(DARK if mode == "dark" else LIGHT)
    red = base == ACCENTS["red"][0]
    if mode == "dark" and not red:
        pal.update(accent=base, accent_hi=_mix(base, "#ffffff", 0.22), accent_lo=_mix(base, "#000000", 0.45),
                   sel=_mix(pal["bg"], base, 0.24), ok=base, bar_paused=_mix(pal["bg"], base, 0.35))
    elif mode == "light":
        pal.update(accent=base, accent_hi=_mix(base, "#000000", 0.12), accent_lo=_mix(base, "#ffffff", 0.55),
                   sel=_mix("#ffffff", base, 0.16), ok=base, bar_paused=_mix("#ffffff", base, 0.35),
                   bar_error=_mix("#ffffff", "#e0641c", 0.45), knob=base)
    C.clear()
    C.update(pal)
    if red and mode == "dark":
        CATEGORY_COLORS.update(_RED_CATEGORIES)
    else:
        strong, hi = C["accent"], C["accent_hi"]
        toward = "#ffffff" if mode == "dark" else "#000000"
        CATEGORY_COLORS.update(video=strong, stream=strong, torrent=hi, program=strong,
                               audio=_mix(strong, toward, 0.25), image=_mix(strong, toward, 0.4),
                               document="#c9c9d2" if mode == "dark" else "#6e6e78",
                               other="#9a9aa5" if mode == "dark" else "#7c7c86",
                               archive="#ff9f43" if mode == "dark" else "#d97a14")
    _ICON_CACHE.clear()
    return mode


def palette():
    """QPalette com as mesmas cores, para o que a folha de estilo não pinta (caixas de mensagem, calendário…)."""
    from PySide6.QtGui import QPalette
    p = QPalette()
    R = QPalette.ColorRole
    for role, key in ((R.Window, "bg"), (R.WindowText, "text"), (R.Base, "panel2"), (R.AlternateBase, "panel"),
                      (R.Text, "text"), (R.Button, "panel3"), (R.ButtonText, "text"), (R.ToolTipBase, "panel3"),
                      (R.ToolTipText, "text"), (R.Highlight, "accent"), (R.HighlightedText, "on_accent"),
                      (R.Link, "accent_hi"), (R.PlaceholderText, "faint"), (R.Mid, "border"), (R.Dark, "panel3"),
                      (R.Light, "panel"), (R.Midlight, "panel2"), (R.Shadow, "bg")):
        p.setColor(role, QColor(C[key]))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(C["faint"]))
    return p

_ICON_FAMILY = None
_ICON_CACHE = {}
_SVG_CACHE = {}
ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons")
# glifos crus usados pelo player -> nome do SVG equivalente
_RAW = {"": "prev", "": "next", "": "volume", "": "mute",
        "": "fullscreen", "": "exit_fullscreen"}


def icon_family():
    """Fonte de ícones do Windows, ou "" quando não existe (Linux/macOS): aí os ícones vêm dos SVGs."""
    global _ICON_FAMILY
    if _ICON_FAMILY is None:
        fams = set(QFontDatabase.families())
        _ICON_FAMILY = "" if os.environ.get("SCARLETDM_SVG_ICONS") else             next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _ICON_FAMILY


def _svg_name(name):
    if name in _RAW:
        return _RAW[name]
    rev = next((k for k, v in G.items() if v == name), None)
    return rev or name


def _svg_pixmap(name, color, size, dpr):
    from PySide6.QtSvg import QSvgRenderer
    key = _svg_name(name)
    body = _SVG_CACHE.get(key)
    if body is None:
        path = os.path.join(ICONS_DIR, key + ".svg")
        if not os.path.isfile(path):
            path = os.path.join(ICONS_DIR, "other.svg")
        with open(path, encoding="utf-8") as f:
            body = _SVG_CACHE[key] = f.read()
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(body.replace("currentColor", color).encode("utf-8"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    m = size * dpr * 0.12
    r.render(p, QRectF(m, m, size * dpr - 2 * m, size * dpr - 2 * m))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def glyph_pixmap(name, color, size=18, dpr=2.0):
    if not icon_family():
        return _svg_pixmap(name, color, size, dpr)
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont(icon_family())
    f.setPixelSize(int(size * dpr * 0.78))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size * dpr, size * dpr), Qt.AlignmentFlag.AlignCenter, G.get(name, name))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def glyph(name, color=None, size=18, hover=None):
    key = (name, color, size, hover)
    ic = _ICON_CACHE.get(key)
    if ic is None:
        ic = QIcon()
        ic.addPixmap(glyph_pixmap(name, color or C["text"], size), QIcon.Mode.Normal)
        ic.addPixmap(glyph_pixmap(name, C["faint"], size), QIcon.Mode.Disabled)
        if hover:
            ic.addPixmap(glyph_pixmap(name, hover, size), QIcon.Mode.Active)
        _ICON_CACHE[key] = ic
    return ic


def category_icon(cat):
    return glyph(cat if cat in G else "other", CATEGORY_COLORS.get(cat, C["muted"]), 18)


def _squircle(r, n=5.0, steps=160):
    import math
    path = QPainterPath()
    cx, cy, a, b = r.center().x(), r.center().y(), r.width() / 2, r.height() / 2
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        x = cx + a * math.copysign(abs(ct) ** (2 / n), ct)
        y = cy + b * math.copysign(abs(st) ** (2 / n), st)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def paint_logo(p, s):
    """Logo: gota escarlate com seta de download sobre um quadrado arredondado preto."""
    from PySide6.QtGui import QRadialGradient
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94)
    bg = QLinearGradient(r.topLeft(), r.bottomLeft())
    bg.setColorAt(0, QColor("#202027"))
    bg.setColorAt(1, QColor("#0a0a0c"))
    p.setPen(QPen(QColor("#2e2e36"), max(1.0, s * 0.01)))
    p.setBrush(bg)
    p.drawPath(_squircle(r))
    cx = s * 0.5
    d = QPainterPath()
    d.moveTo(cx, s * 0.12)
    d.cubicTo(QPointF(cx + s * 0.08, s * 0.28), QPointF(cx + s * 0.30, s * 0.42), QPointF(cx + s * 0.30, s * 0.60))
    d.cubicTo(QPointF(cx + s * 0.30, s * 0.78), QPointF(cx + s * 0.16, s * 0.89), QPointF(cx, s * 0.89))
    d.cubicTo(QPointF(cx - s * 0.16, s * 0.89), QPointF(cx - s * 0.30, s * 0.78), QPointF(cx - s * 0.30, s * 0.60))
    d.cubicTo(QPointF(cx - s * 0.30, s * 0.42), QPointF(cx - s * 0.08, s * 0.28), QPointF(cx, s * 0.12))
    d.closeSubpath()
    g = QLinearGradient(QPointF(cx - s * 0.3, s * 0.12), QPointF(cx + s * 0.3, s * 0.89))
    g.setColorAt(0, QColor("#ff5a66"))
    g.setColorAt(0.55, QColor("#e3222f"))
    g.setColorAt(1, QColor("#9a101a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(d)
    if s >= 32:   # brilho só onde dá para ver
        hl = QRadialGradient(QPointF(cx - s * 0.15, s * 0.46), s * 0.09)
        hl.setColorAt(0, QColor(255, 255, 255, 95))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawEllipse(QPointF(cx - s * 0.15, s * 0.46), s * 0.09, s * 0.09)
    pen = QPen(QColor("#ffffff"), max(1.6, s * 0.075))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(cx, s * 0.45), QPointF(cx, s * 0.73))
    a = QPainterPath(QPointF(cx - s * 0.12, s * 0.62))
    a.lineTo(QPointF(cx, s * 0.74))
    a.lineTo(QPointF(cx + s * 0.12, s * 0.62))
    p.drawPath(a)


def app_icon_pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_logo(p, float(size))
    p.end()
    return pm


def app_icon():
    ic = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(app_icon_pixmap(sz))
    return ic


def _write_assets():
    d = os.path.join(app_data_dir(), "ui")
    os.makedirs(d, exist_ok=True)
    svgs = {
        "check.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" '
                     'fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "check_menu.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" '
                          f'fill="none" stroke="{C["accent_hi"]}" stroke-width="2" stroke-linecap="round" '
                          'stroke-linejoin="round"/></svg>',
        "chevron.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" '
                       f'fill="none" stroke="{C["muted"]}" stroke-width="1.8" stroke-linecap="round"/></svg>',
        "up.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 10l4-4 4 4" '
                  f'fill="none" stroke="{C["muted"]}" stroke-width="1.8" stroke-linecap="round"/></svg>',
        "radio.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3.5" '
                     'fill="#ffffff"/></svg>',
    }
    for name, body in svgs.items():
        path = os.path.join(d, name)
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != body:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
    return d.replace("\\", "/")


def stylesheet():
    a = _write_assets()
    c = C
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Noto Sans",
     "Cantarell", "Ubuntu", "DejaVu Sans", sans-serif; font-size: 10pt; color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QWidget#Player {{ background: {c['bg']}; }}
QWidget#DialogFoot {{ background: {c['bg']}; border-top: 1px solid {c['border']}; }}
QSlider::groove:horizontal {{ height: 5px; background: {c['track']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 13px; height: 13px; margin: -5px 0; border-radius: 6px; background: {c['knob']}; }}
QSlider::handle:horizontal:hover {{ background: {c['accent_hi']}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget#qt_scrollarea_viewport, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QStackedWidget {{ background: {c['bg']}; }}
QWidget#TopBar {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
QWidget#FilterBar {{ background: {c['bg']}; border-bottom: 1px solid {c['border']}; }}
QWidget#StatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; }}
QWidget#Banner {{ background: {c['sel']}; border-bottom: 1px solid {c['accent_lo']}; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px; }}
QToolButton:hover {{ background: {c['panel3']}; }}
QToolButton:pressed {{ background: {c['accent_lo']}; }}
QToolButton:checked {{ background: {c['sel']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton#AddButton {{ background: {c['accent']}; border-radius: 8px; }}
QToolButton#AddButton:hover {{ background: {c['accent_hi']}; }}
QToolButton#AddButton:pressed {{ background: {c['accent_lo']}; }}
QToolButton#StatusChip {{ color: {c['muted']}; padding: 3px 8px; border-radius: 5px; }}
QToolButton#StatusChip:hover {{ color: {c['text']}; background: {c['panel3']}; }}
QToolButton#StatusChip:checked {{ color: {c['text']}; background: {c['sel']}; }}
QPushButton#Filter {{ background: transparent; border: none; border-bottom: 2px solid transparent;
    border-radius: 0; padding: 8px 10px 6px 10px; color: {c['muted']}; }}
QPushButton#Filter:hover {{ color: {c['text']}; }}
QPushButton#Filter:checked {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QTableView {{ background: {c['bg']}; border: none; gridline-color: transparent;
    selection-background-color: {c['sel']}; selection-color: {c['text']}; outline: 0; }}
QTableView::item {{ border-bottom: 1px solid {c['row']}; padding-left: 4px; }}
QTableView::item:hover {{ background: {c['hover']}; }}
QTableView::item:selected {{ background: {c['sel']}; }}
QHeaderView {{ background: {c['panel']}; }}
QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['border']}; border-right: 1px solid {c['border']}; padding: 6px 8px; }}
QHeaderView::section:hover {{ color: {c['text']}; }}
QHeaderView::down-arrow, QHeaderView::up-arrow {{ width: 0; height: 0; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent_lo']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['accent_lo']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QTimeEdit {{ background: {c['panel2']};
    border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {c['faint']}; }}
QLineEdit#Search {{ background: {c['panel2']}; border-radius: 16px; padding: 6px 12px; }}
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{
    background: transparent; border: none; width: 18px; }}
QSpinBox::up-arrow, QTimeEdit::up-arrow {{ image: url({a}/up.svg); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QTimeEdit::down-arrow {{ image: url({a}/chevron.svg); width: 10px; height: 10px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({a}/chevron.svg); width: 11px; height: 11px; }}
QComboBox QAbstractItemView {{ background: {c['panel2']}; border: 1px solid {c['border']};
    selection-background-color: {c['sel']}; outline: 0; padding: 4px; }}
QPushButton {{ background: {c['panel3']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 7px 16px; }}
QPushButton:hover {{ border-color: {c['accent_lo']}; background: {c['btn_hover']}; }}
QPushButton:pressed {{ background: {c['accent_lo']}; }}
QPushButton:disabled {{ color: {c['faint']}; }}
QPushButton#Primary {{ background: {c['accent']}; border: 1px solid {c['accent']}; color: {c['on_accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {c['accent_hi']}; border-color: {c['accent_hi']}; }}
QPushButton#Link {{ background: transparent; border: none; color: {c['accent_hi']}; padding: 2px; text-align: left; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QMenu {{ background: {c['panel2']}; border: 1px solid {c['border']}; padding: 6px; }}
QMenu::item {{ padding: 7px 30px 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['sel']}; }}
QMenu::item:disabled {{ color: {c['faint']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 6px; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::indicator:checked {{ image: url({a}/check_menu.svg); width: 14px; height: 14px; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {c['border']}; background: {c['panel']}; }}
QTabWidget#Details::pane {{ background: {c['panel']}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 8px 14px; border: none;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['box_border']}; border-radius: 4px; background: {c['panel2']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({a}/check.svg); }}
QCheckBox:disabled {{ color: {c['faint']}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {c['box_border']}; border-radius: 8px; background: {c['panel2']}; }}
QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({a}/radio.svg); }}
QToolTip {{ background: {c['panel3']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
QSplitter::handle {{ background: {c['border']}; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 16px; padding: 14px 12px 12px 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {c['muted']}; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Faint {{ color: {c['faint']}; }}
QLabel#H1 {{ font-size: 15pt; font-weight: 600; }}
QLabel#H2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#Error {{ color: {c['error']}; }}
QLabel#Empty {{ color: {c['faint']}; font-size: 12pt; }}
QListWidget, QTreeWidget, QTableWidget {{ background: {c['panel2']}; border: 1px solid {c['border']};
    border-radius: 6px; outline: 0; alternate-background-color: {c['panel']}; }}
QListWidget::item, QTreeWidget::item {{ padding: 5px; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {c['sel']}; }}
QListWidget#SideNav {{ background: {c['panel']}; border: none; border-right: 1px solid {c['border']}; border-radius: 0; padding: 8px; }}
QListWidget#SideNav::item {{ padding: 9px 10px; border-radius: 6px; color: {c['muted']}; }}
QListWidget#SideNav::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QListWidget#SideNav::item:hover {{ color: {c['text']}; }}
"""


def bring_to_front(widget):
    """Traz a janela para a frente mesmo com outro programa em foco (ex.: o navegador que mandou o link).

    O Windows bloqueia SetForegroundWindow de apps em segundo plano e só faz o ícone piscar na barra. A saída
    documentada é "anexar" a fila de entrada à da janela que está na frente durante a troca de foco."""
    widget.show()
    if widget.isMinimized():
        widget.showNormal()
    widget.raise_()
    widget.activateWindow()
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        for name in ("SetForegroundWindow", "BringWindowToTop", "SetActiveWindow", "SetFocus", "IsIconic"):
            getattr(u32, name).argtypes = [wintypes.HWND]
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint]
        hwnd = wintypes.HWND(int(widget.winId()))
        fg = u32.GetForegroundWindow()
        if fg == hwnd.value:
            return
        me = k32.GetCurrentThreadId()
        other = u32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(other and other != me and u32.AttachThreadInput(me, other, True))
        try:
            u32.ShowWindow(hwnd, 9 if u32.IsIconic(hwnd) else 5)          # SW_RESTORE / SW_SHOW
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
            u32.SetActiveWindow(hwnd)
            u32.SetFocus(hwnd)
        finally:
            if attached:
                u32.AttachThreadInput(me, other, False)
        if u32.GetForegroundWindow() != hwnd.value:
            # último recurso: fica por cima de tudo por um instante (aparece na tela mesmo sem o foco)
            flags = 0x0001 | 0x0002 | 0x0040                                  # NOSIZE | NOMOVE | SHOWWINDOW
            u32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)     # HWND_TOPMOST
            u32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)     # HWND_NOTOPMOST
            u32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def keep_on_screen(widget, margin=40):
    """Encolhe e reposiciona a janela para caber inteira na tela (notebooks 1366x768, zoom de 125%/150%).
    Janelas maximizadas ou em tela cheia ficam como estão."""
    if widget.isMaximized() or widget.isFullScreen():
        return
    from PySide6.QtWidgets import QApplication
    screen = (widget.windowHandle().screen() if widget.windowHandle() else None) or QApplication.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    frame = widget.frameGeometry()
    extra_w, extra_h = frame.width() - widget.width(), frame.height() - widget.height()   # bordas e barra de título
    w = min(widget.width(), avail.width() - margin - extra_w)
    h = min(widget.height(), avail.height() - margin - extra_h)
    if (w, h) != (widget.width(), widget.height()):
        widget.resize(max(w, widget.minimumWidth()), max(h, min(widget.minimumHeight(), h)))
    frame = widget.frameGeometry()
    x = min(max(frame.left(), avail.left()), avail.right() - frame.width() + 1)
    y = min(max(frame.top(), avail.top()), avail.bottom() - frame.height() + 1)
    if (x, y) != (frame.left(), frame.top()):
        widget.move(x, max(avail.top(), y))


def apply_dark_titlebar(widget):
    """Barra de título nas cores do tema (escura ou clara, borda na cor de destaque) no Windows 11 (DWM)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi

        def setattr_(attr, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        def bgr(hexcolor):
            h = hexcolor.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (b << 16) | (g << 8) | r

        setattr_(20, 1 if is_dark() else 0)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        setattr_(35, bgr(C["panel"]))       # DWMWA_CAPTION_COLOR
        setattr_(34, bgr(C["accent_lo"]))   # DWMWA_BORDER_COLOR
        setattr_(36, bgr(C["text"]))        # DWMWA_TEXT_COLOR
    except Exception:
        pass


def pen(color, width=1.0):
    p = QPen(QColor(color))
    p.setWidthF(width)
    return p


__all__ = ["C", "G", "ACCENTS", "apply_theme", "palette", "is_dark", "glyph", "glyph_pixmap", "category_icon", "app_icon", "app_icon_pixmap", "stylesheet",
           "apply_dark_titlebar", "pen", "QPointF"]
