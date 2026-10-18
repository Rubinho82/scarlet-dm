"""Janela "Nova versão disponível": mostra o que mudou, baixa, confere e instala a atualização."""
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout)

from .. import APP_NAME, VERSION, updater
from ..i18n import _, current
from ..util import format_size, open_path
from .theme import apply_dark_titlebar, keep_on_screen
from .setup_ui import logo_label


class _Sig(QObject):
    progress = Signal(int, int)
    done = Signal(str, str)         # caminho, erro


class UpdateDialog(QDialog):
    def __init__(self, info, settings, parent=None, quit_app=None):
        super().__init__(parent)
        self.info, self.st, self.quit_app = info, settings, quit_app
        self._cancel = False
        self.setWindowTitle(_("Atualização do {app}").format(app=APP_NAME))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(logo_label(48))
        col = QVBoxLayout()
        title = QLabel(_("Nova versão disponível: {v}").format(v=info["version"]))
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        sub = QLabel(_("Você está na versão {v}. Sua lista de downloads e suas configurações são mantidas.")
                     .format(v=VERSION))
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        col.addWidget(title)
        col.addWidget(sub)
        head.addLayout(col, 1)
        v.addLayout(head)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.get("notes") or _("Correções e melhorias."))
        notes.setMaximumHeight(220)
        v.addWidget(notes)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        v.addWidget(self.status)
        v.addWidget(self.bar)
        btns = QHBoxLayout()
        self.skip = QPushButton(_("Pular esta versão"))
        self.skip.clicked.connect(self._skip)
        btns.addWidget(self.skip)
        btns.addStretch(1)
        self.later = QPushButton(_("Depois"))
        self.later.clicked.connect(self.reject)
        self.go = QPushButton()
        self.go.setObjectName("Primary")
        self.go.setDefault(True)
        self.auto = updater.can_auto_update(info)
        self.go.setText(_("Atualizar agora") if self.auto else _("Abrir página de download"))
        self.go.clicked.connect(self._go)
        btns.addWidget(self.later)
        btns.addWidget(self.go)
        v.addLayout(btns)
        self.sig = _Sig()
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._done)

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))

    def _skip(self):
        self.st["update_skip"] = self.info["version"]
        self.st.save()
        self.reject()

    def _go(self):
        if not self.auto:
            open_path(self.info.get("page") or updater.SITE)
            self.accept()
            return
        self.go.setEnabled(False)
        self.skip.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText(_("Baixando a atualização…"))

        def work():
            try:
                path = updater.prepare(self.info, lambda d, t: self.sig.progress.emit(d, t), lambda: self._cancel)
                self.sig.done.emit(path, "")
            except Exception as e:  # noqa: BLE001 - mostra o motivo para a pessoa
                self.sig.done.emit("", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, done, total):
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.status.setText(_("Baixando a atualização… {a} de {b}").format(a=format_size(done), b=format_size(total)))

    def _done(self, path, err):
        if self._cancel:
            return
        if err:
            msg = {"bad-checksum": _("O arquivo baixado não confere com a soma SHA-256 publicada; nada foi instalado."),
                   "no-checksum": _("Este lançamento não tem soma SHA-256 para conferir; nada foi instalado.")}.get(
                err, _("Não foi possível baixar a atualização: {e}").format(e=err))
            r = QMessageBox.warning(self, APP_NAME, msg + "\n\n" + _("Abrir a página de download?"),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Yes:
                open_path(self.info.get("page") or updater.SITE)
            self.reject()
            return
        self.status.setText(_("Instalando… o Scarlet DM vai fechar e abrir de novo sozinho."))
        self.bar.setRange(0, 0)
        if updater.apply(path, current()):
            QTimer.singleShot(600, self.quit_app or self.accept)
        else:
            self.accept()

    def reject(self):
        self._cancel = True
        super().reject()
