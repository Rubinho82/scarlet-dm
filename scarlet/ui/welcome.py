"""Boas-vindas na primeira abertura: idioma, pasta de downloads, iniciar com o Windows e atalho.

Quem instala pelo Setup já respondeu isso lá (o instalador marca welcome_done); aparece para a versão portátil.
"""
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from .. import i18n
from ..i18n import _
from . import theme
from .setup_ui import header


class WelcomeDialog(QDialog):
    def __init__(self, settings):
        super().__init__()
        self.st = settings
        self.setMinimumWidth(620)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        hdr, self.subtitle = header("")
        v.addLayout(hdr)
        v.addSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.lang = QComboBox()
        for code, name in i18n.LANGUAGES:
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(i18n.current())))
        self.lang.currentIndexChanged.connect(self._lang_changed)
        self.lang_label = QLabel()
        form.addRow(self.lang_label, self.lang)
        row = QHBoxLayout()
        self.folder = QLineEdit(settings["download_dir"])
        self.browse = QPushButton()
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(self.browse)
        self.folder_label = QLabel()
        form.addRow(self.folder_label, row)
        v.addLayout(form)
        v.addSpacing(6)
        self.c_auto = QCheckBox()
        v.addWidget(self.c_auto)
        self.c_desktop = QCheckBox()
        self.c_desktop.setChecked(True)
        # atalho só faz sentido no .exe que não passou pelo instalador
        self.can_shortcut = bool(getattr(sys, "frozen", False)) and os.name == "nt"
        self.c_desktop.setVisible(self.can_shortcut)
        v.addWidget(self.c_desktop)
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        self.tip.setObjectName("Muted")
        v.addSpacing(6)
        v.addWidget(self.tip)
        v.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.go = QPushButton()
        self.go.setObjectName("Primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self._save)
        btns.addWidget(self.go)
        v.addLayout(btns)
        self.retranslate()
        QTimer.singleShot(0, lambda: theme.apply_dark_titlebar(self))

    def retranslate(self):
        self.setWindowTitle(_("Bem-vindo ao Scarlet DM"))
        self.subtitle.setText(_("Vamos deixar tudo pronto em 10 segundos."))
        self.lang_label.setText(_("Idioma"))
        self.folder_label.setText(_("Salvar downloads em"))
        self.browse.setText(_("Procurar…"))
        self.c_auto.setText(_("Iniciar com o Windows (minimizado perto do relógio)"))
        self.c_desktop.setText(_("Criar atalho na Área de Trabalho"))
        self.tip.setText(_("Dica: para baixar direto do navegador, instale a extensão em Preferências › Navegador. "
                           "Tudo isto pode ser mudado depois nas Preferências."))
        self.go.setText(_("Começar"))

    def _lang_changed(self):
        i18n.set_language(self.lang.currentData())
        self.retranslate()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, _("Escolher pasta"), self.folder.text())
        if d:
            self.folder.setText(os.path.normpath(d))

    def _save(self):
        from .. import autostart, install
        self.st["language"] = self.lang.currentData()
        folder = self.folder.text().strip()
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
                self.st["download_dir"] = folder
            except OSError:
                pass
        try:
            autostart.set_enabled(self.c_auto.isChecked())
        except OSError:
            pass
        if self.can_shortcut and self.c_desktop.isChecked():
            try:
                install.create_shortcut(install.shortcut_paths()["desktop"], sys.executable)
            except OSError:
                pass
        self.st["welcome_done"] = True
        self.st.save()
        self.accept()

    def reject(self):
        # fechar no X/Esc também conta como "já vi": não perguntar de novo a cada abertura
        self.st["welcome_done"] = True
        self.st["language"] = self.lang.currentData()
        self.st.save()
        super().reject()
