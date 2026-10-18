"""Reprodutor de vídeo e música embutido (Qt Multimedia, backend FFmpeg do próprio Qt).

O vídeo é desenhado numa janela nativa que "engole" teclado e mouse; por isso os atalhos e os cliques
no vídeo são tratados por um filtro de eventos no nível do aplicativo enquanto o reprodutor está aberto.
"""
import os

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QSlider, QStackedWidget, QStyle,
                               QStyleOptionSlider, QToolButton, QToolTip, QVBoxLayout, QWidget)

from ..i18n import _
from ..util import reveal_in_folder
from .theme import C, apply_dark_titlebar, app_icon, glyph, keep_on_screen
from .thumbs import AUDIO_EXTS, fmt_duration

G_PREV, G_NEXT, G_VOL, G_MUTE = "", "", "", ""
G_FULL, G_EXIT_FULL = "", ""


class ClickSlider(QSlider):
    """Slider que pula para onde você clica e mostra o tempo ao passar o mouse."""
    jumped = Signal(int)

    def __init__(self, show_time=False):
        super().__init__(Qt.Orientation.Horizontal)
        self.show_time = show_time
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _value_at(self, x):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                             QStyle.SubControl.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                             QStyle.SubControl.SC_SliderHandle, self)
        span = max(1, groove.width() - handle.width())
        pos = min(max(0, x - groove.x() - handle.width() // 2), span)
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, span)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            v = self._value_at(int(e.position().x()))
            self.setValue(v)
            self.jumped.emit(v)
            self.setSliderDown(True)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        x = int(e.position().x())
        if self.isSliderDown():
            v = self._value_at(x)
            self.setValue(v)
            self.jumped.emit(v)
        if self.show_time and self.maximum() > 0:
            QToolTip.showText(self.mapToGlobal(QPoint(x, -28)), fmt_duration(self._value_at(x) / 1000), self)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False)
            self.jumped.emit(self.value())
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)


class PlayerWindow(QWidget):
    def __init__(self, thumbs=None):
        super().__init__()
        self.thumbs = thumbs
        self.setWindowTitle(_("Scarlet DM — Reprodutor"))
        self.setWindowIcon(app_icon())
        self.resize(960, 600)
        self.setMinimumSize(460, 320)
        self.setObjectName("Player")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.items = []          # [(caminho, título, tarefa)]
        self.index = 0
        self._filter_on = False

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.video = QVideoWidget()
        self.video.setStyleSheet("background:#000;")
        self.video.setMouseTracking(True)
        self.player.setVideoOutput(self.video)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet("background:#000;")
        self.stack.addWidget(self.video)
        self.stack.addWidget(self.cover)
        lay.addWidget(self.stack, 1)

        self.bar = QWidget()
        self.bar.setObjectName("StatusBar")
        self.bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(14, 8, 14, 10)
        bl.setSpacing(4)
        trow = QHBoxLayout()
        self.title = QLabel("")
        self.title.setObjectName("H2")
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        trow.addWidget(self.title, 1)
        trow.addWidget(self.hint)
        bl.addLayout(trow)
        srow = QHBoxLayout()
        self.pos_lbl = QLabel("0:00")
        self.pos_lbl.setObjectName("Muted")
        self.slider = ClickSlider(show_time=True)
        self.slider.setRange(0, 0)
        self.slider.jumped.connect(self._seek)
        self.dur_lbl = QLabel("0:00")
        self.dur_lbl.setObjectName("Muted")
        srow.addWidget(self.pos_lbl)
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.dur_lbl)
        bl.addLayout(srow)
        crow = QHBoxLayout()
        self.b_prev = self._btn(G_PREV, _("Anterior (P)"), self.prev)
        self.b_play = self._btn("play", _("Reproduzir/pausar (Espaço)"), self.toggle_play, size=22)
        self.b_next = self._btn(G_NEXT, _("Próximo (N)"), self.next)
        self.b_mute = self._btn(G_VOL, _("Mudo (M)"), self.toggle_mute)
        self.vol = ClickSlider()
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setFixedWidth(110)
        self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        self.b_folder = self._btn("folder", _("Abrir pasta"), self._open_folder)
        self.b_full = self._btn(G_FULL, _("Tela cheia (F)"), self.toggle_fullscreen)
        for w in (self.b_prev, self.b_play, self.b_next):
            crow.addWidget(w)
        crow.addSpacing(10)
        crow.addWidget(self.b_mute)
        crow.addWidget(self.vol)
        crow.addSpacing(12)
        crow.addWidget(self.info, 1)
        crow.addWidget(self.b_folder)
        crow.addWidget(self.b_full)
        bl.addLayout(crow)
        lay.addWidget(self.bar)

        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)

        # em tela cheia, os controles somem depois de um tempo parado e voltam ao mexer o mouse
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(2500)
        self._hide_timer.timeout.connect(self._auto_hide)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(QApplication.doubleClickInterval())
        self._click_timer.timeout.connect(self.toggle_play)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(lambda: self.hint.setText(""))
        self._last_mouse = QPoint()
        # rede de segurança: em tela cheia, olha a posição real do cursor (a janela nativa do vídeo
        # nem sempre repassa o movimento do mouse)
        self._poll = QTimer(self)
        self._poll.setInterval(300)
        self._poll.timeout.connect(self._poll_mouse)

    def _poll_mouse(self):
        if not self.isFullScreen():
            self._poll.stop()
            return
        gp = QCursor.pos()
        if (gp - self._last_mouse).manhattanLength() > 2:
            self._last_mouse = gp
            if not self.bar.isVisible() or not self._hide_timer.isActive():
                self._show_controls()
            else:
                self._hide_timer.start()

    def _btn(self, icon, tip, slot, size=18):
        b = QToolButton()
        b.setIcon(glyph(icon, C["text"], size))
        b.setIconSize(b.iconSize().__class__(size, size))
        b.setToolTip(tip)
        b.setFixedSize(38, 34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ---------- ciclo de vida ----------
    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))
        if not self._filter_on:
            QApplication.instance().installEventFilter(self)
            self._filter_on = True

    def closeEvent(self, e):
        self.player.stop()
        self.player.setSource(QUrl())
        self._exit_full()
        if self._filter_on:
            QApplication.instance().removeEventFilter(self)
            self._filter_on = False
        super().closeEvent(e)

    def _mine(self, obj):
        """O evento é de algum pedaço desta janela (inclusive a janela nativa do vídeo)?"""
        w = obj if isinstance(obj, QWidget) else None
        if w is not None:
            return w.window() is self
        return self.isActiveWindow()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.KeyPress and self._mine(obj):
            if self._key(ev):
                return True
        elif t == QEvent.Type.MouseMove and self.isFullScreen():
            gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else QCursor.pos()
            if (gp - self._last_mouse).manhattanLength() > 2:
                self._last_mouse = gp
                self._show_controls()
        elif t in (QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonPress) and self._mine(obj):
            gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else QCursor.pos()
            if ev.button() == Qt.MouseButton.LeftButton and self._over_video(gp):
                if t == QEvent.Type.MouseButtonDblClick:
                    self._click_timer.stop()
                    self.toggle_fullscreen()
                else:
                    self._click_timer.start()
                return True
        return False

    def _over_video(self, gp=None):
        """O clique foi na área do vídeo (e não na barra de controles)? Usa a posição do próprio evento."""
        w = self.stack.currentWidget()
        r = w.rect().translated(w.mapToGlobal(QPoint(0, 0)))
        return r.contains(gp if gp is not None else QCursor.pos())

    def _key(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self._exit_full()
                return True
            return False
        actions = {
            Qt.Key.Key_Space: self.toggle_play, Qt.Key.Key_K: self.toggle_play,
            Qt.Key.Key_F: self.toggle_fullscreen, Qt.Key.Key_F11: self.toggle_fullscreen,
            Qt.Key.Key_M: self.toggle_mute, Qt.Key.Key_N: self.next, Qt.Key.Key_P: self.prev,
            Qt.Key.Key_Right: lambda: self._jump(5000), Qt.Key.Key_Left: lambda: self._jump(-5000),
            Qt.Key.Key_L: lambda: self._jump(10000), Qt.Key.Key_J: lambda: self._jump(-10000),
            Qt.Key.Key_Up: lambda: self.vol.setValue(self.vol.value() + 5),
            Qt.Key.Key_Down: lambda: self.vol.setValue(self.vol.value() - 5),
        }
        fn = actions.get(k)
        if fn is None:
            return False
        fn()
        if self.isFullScreen():
            self._show_controls()
        return True

    # ---------- lista ----------
    def play_items(self, items, start=0):
        self.items = [it for it in items if os.path.exists(it[0])]
        if not self.items:
            return
        self.index = max(0, min(start, len(self.items) - 1))
        multi = len(self.items) > 1
        self.b_prev.setVisible(multi)
        self.b_next.setVisible(multi)
        self._load()
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _load(self):
        path, title, task = self.items[self.index]
        self.title.setText(title + (f"   ({self.index + 1}/{len(self.items)})" if len(self.items) > 1 else ""))
        self.setWindowTitle(_('{title} — Scarlet DM').format(title=title))
        is_audio = os.path.splitext(path)[1].lstrip(".").lower() in AUDIO_EXTS
        self.stack.setCurrentIndex(1 if is_audio else 0)
        if is_audio:
            pm = self.thumbs.pixmap(task) if (self.thumbs and task) else None
            if pm:
                self.cover.setPixmap(pm.scaled(420, 420, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
            else:
                self.cover.setPixmap(glyph("audio", C["accent"], 120).pixmap(120, 120))
        info = self.thumbs.describe(self.thumbs.info(task)) if (self.thumbs and task) else ""
        self.info.setText(info)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def next(self):
        if self.index + 1 < len(self.items):
            self.index += 1
            self._load()

    def prev(self):
        if self.player.position() > 3000 or self.index == 0:
            self.player.setPosition(0)
            return
        self.index -= 1
        self._load()

    # ---------- controles ----------
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self.b_mute.setIcon(glyph(G_MUTE if self.audio.isMuted() else G_VOL, C["text"], 18))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_full()
        else:
            self.showFullScreen()
            self.b_full.setIcon(glyph(G_EXIT_FULL, C["text"], 18))
            self.b_full.setToolTip(_("Sair da tela cheia (Esc)"))
            self._flash_hint(_("Esc ou duplo clique para sair da tela cheia"))
            self._last_mouse = QCursor.pos()
            self._poll.start()
            self._show_controls()

    def _exit_full(self):
        self._hide_timer.stop()
        self.bar.show()
        self.unsetCursor()
        self.video.unsetCursor()
        if self.isFullScreen():
            self.showNormal()
        self.b_full.setIcon(glyph(G_FULL, C["text"], 18))
        self.b_full.setToolTip(_("Tela cheia (F)"))

    def _show_controls(self):
        self.bar.show()
        self.video.unsetCursor()
        self.unsetCursor()
        if self.isFullScreen():
            self._hide_timer.start()

    def _auto_hide(self):
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        under_bar = self.bar.isVisible() and self.bar.rect().translated(
            self.bar.mapToGlobal(QPoint(0, 0))).contains(QCursor.pos())
        if self.isFullScreen() and playing and not under_bar:
            self.bar.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.video.setCursor(Qt.CursorShape.BlankCursor)
        elif self.isFullScreen():
            self._hide_timer.start()

    def _flash_hint(self, text, ms=4000):
        self.hint.setText(text)
        self._hint_timer.start(ms)

    def _jump(self, ms):
        self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + ms)))

    def _seek(self, ms):
        self.player.setPosition(ms)
        self.pos_lbl.setText(fmt_duration(ms / 1000))

    def _open_folder(self):
        if self.items:
            reveal_in_folder(self.items[self.index][0])

    # ---------- eventos do player ----------
    def _on_pos(self, ms):
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(ms)
            self.slider.blockSignals(False)
            self.pos_lbl.setText(fmt_duration(ms / 1000))

    def _on_dur(self, ms):
        self.slider.setRange(0, ms)
        self.dur_lbl.setText(fmt_duration(ms / 1000))

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.b_play.setIcon(glyph("pause" if playing else "play", C["text"], 22))
        if not playing and self.isFullScreen():
            self._show_controls()

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.index + 1 < len(self.items):
            self.next()

    def _on_error(self, err, text):
        self.info.setText(_("Não foi possível reproduzir: {erro}. Use “Abrir” para tocar em outro programa.")
                          .format(erro=text or err))
