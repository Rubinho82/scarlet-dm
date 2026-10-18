"""Menu › Relatar problema: gera o .zip do relatório e/ou abre a página de relatos no GitHub."""
import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from .. import APP_NAME, report
from ..i18n import _
from ..util import open_path, reveal_in_folder
from .theme import apply_dark_titlebar, keep_on_screen


class ReportDialog(QDialog):
    def __init__(self, settings, manager, parent=None):
        super().__init__(parent)
        self.st, self.m = settings, manager
        self.setWindowTitle(_("Relatar problema"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(10)
        h = QLabel(_("Relatar problema"))
        h.setObjectName("H1")
        v.addWidget(h)
        v.addWidget(QLabel(_("O que aconteceu? (o que você fez, o que esperava e o que apareceu)")))
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText(_("Ex.: cliquei em Baixar num vídeo do YouTube e apareceu “erro 403”."))
        self.desc.setMinimumHeight(110)
        v.addWidget(self.desc)
        self.with_list = QCheckBox(_("Incluir os últimos downloads (nome, site e erro — sem os links completos)"))
        self.with_list.setChecked(True)
        v.addWidget(self.with_list)
        note = QLabel(_("O relatório não leva senhas nem cookies. Você pode abrir o .zip e conferir antes de mandar."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        v.addWidget(note)
        btns = QHBoxLayout()
        gh = QPushButton(_("Abrir página de relatos (GitHub)"))
        gh.clicked.connect(lambda: open_path(report.issue_url()))
        btns.addWidget(gh)
        btns.addStretch(1)
        close = QPushButton(_("Fechar"))
        close.clicked.connect(self.reject)
        save = QPushButton(_("Salvar relatório…"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        btns.addWidget(close)
        btns.addWidget(save)
        v.addLayout(btns)

    def showEvent(self, e):
        super().showEvent(e)
        apply_dark_titlebar(self)
        QTimer.singleShot(0, lambda: keep_on_screen(self))

    def _save(self):
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        folder = desk if os.path.isdir(desk) else os.path.expanduser("~")
        default = os.path.join(folder, f"ScarletDM-relatorio-{time.strftime('%Y%m%d-%H%M')}.zip")
        path, _flt = QFileDialog.getSaveFileName(self, _("Salvar relatório"), default, "ZIP (*.zip)")
        if not path:
            return
        try:
            report.build(path, self.desc.toPlainText(), self.st, self.m, self.with_list.isChecked())
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, _("Não foi possível salvar: {e}").format(e=e))
            return
        reveal_in_folder(path)
        QMessageBox.information(self, APP_NAME, _("Relatório salvo. Mande esse arquivo junto com o seu relato "
                                                  "(no GitHub, no Discord ou por mensagem)."))
        self.accept()
