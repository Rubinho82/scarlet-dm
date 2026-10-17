"""Telas do instalador (installer/setup.py) e do desinstalador (ScarletDM.exe --uninstall)."""
import json
import os
import shutil
import sys
import threading
import zipfile

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, VERSION, i18n, install
from ..i18n import _
from . import theme


def logo_label(size=56):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    theme.paint_logo(p, size * 2)
    p.end()
    pm.setDevicePixelRatio(2.0)
    lab = QLabel()
    lab.setPixmap(pm)
    lab.setFixedSize(size, size)
    return lab


def header(subtitle):
    row = QHBoxLayout()
    row.setSpacing(14)
    row.addWidget(logo_label())
    col = QVBoxLayout()
    col.setSpacing(2)
    title = QLabel(APP_NAME)
    title.setStyleSheet("font-size: 22px; font-weight: 700;")
    sub = QLabel(subtitle)
    sub.setObjectName("Muted")
    col.addWidget(title)
    col.addWidget(sub)
    row.addLayout(col, 1)
    return row, sub


def close_running(parent, only_dir):
    """Fecha o Scarlet DM aberto desta pasta antes de mexer nos arquivos (cópias portáteis em outras pastas não
    são tocadas). Devolve False se o usuário cancelar."""
    while True:
        running = install.running_instances(only_dir)
        if not running:
            return True
        for _pid, path in running:
            install.ask_to_quit(path)
        if install.wait_closed([p for p, _x in running], 10):
            return True
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(_("O Scarlet DM está aberto. Feche-o (ícone perto do relógio → Sair) e clique em "
                      "“Tentar de novo”."))
        retry = box.addButton(_("Tentar de novo"), QMessageBox.ButtonRole.AcceptRole)
        force = box.addButton(_("Fechar para mim"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is force:
            for pid, _path in install.running_instances(only_dir):
                install.terminate(pid)
            install.wait_closed([p for p, _x in running], 5)
        elif box.clickedButton() is not retry:
            return False


def payload_size(payload):
    try:
        with zipfile.ZipFile(payload) as z:
            return sum(i.file_size for i in z.infolist())
    except (OSError, zipfile.BadZipFile):
        return 0


# ====================================================================== instalador
class _Worker(QObject):
    progress = Signal(int, str)
    finished = Signal(str)        # "" = ok, senão a mensagem de erro


class InstallerWindow(QDialog):
    """payload = zip com o conteúdo da pasta dist/ScarletDM."""

    def __init__(self, payload, opts=None):
        super().__init__()
        self.payload = payload
        self.opts = opts or {}
        self.need = payload_size(payload)
        self.target = ""
        self.setMinimumSize(660, 520)
        self.stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        hdr, self.subtitle = header("")
        outer.addLayout(hdr)
        outer.addSpacing(10)
        outer.addWidget(self.stack, 1)
        self._build_options()
        self._build_progress()
        self._build_done()
        self.retranslate()
        self.worker = _Worker()
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        QTimer.singleShot(0, lambda: theme.apply_dark_titlebar(self))

    # ---------------------------------------------------------- páginas
    def _build_options(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
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
        self.dir = QLineEdit(self.opts.get("dir") or install.installed_dir() or install.default_dir())
        self.browse = QPushButton()
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.dir, 1)
        row.addWidget(self.browse)
        self.dir_label = QLabel()
        form.addRow(self.dir_label, row)
        v.addLayout(form)
        v.addSpacing(6)
        self.c_desktop = QCheckBox()
        self.c_desktop.setChecked(not self.opts.get("no_desktop"))
        self.c_start = QCheckBox()
        self.c_start.setChecked(not self.opts.get("no_startmenu"))
        self.c_auto = QCheckBox()
        self.c_auto.setChecked(bool(self.opts.get("autostart")))
        self.c_assoc = QCheckBox()
        self.c_assoc.setChecked(not self.opts.get("no_handlers"))
        for c in (self.c_desktop, self.c_start, self.c_auto, self.c_assoc):
            v.addWidget(c)
        v.addStretch(1)
        self.space = QLabel()
        self.space.setObjectName("Muted")
        v.addWidget(self.space)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel = QPushButton()
        self.cancel.clicked.connect(self.reject)
        self.go = QPushButton()
        self.go.setObjectName("Primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self.start_install)
        btns.addWidget(self.cancel)
        btns.addWidget(self.go)
        v.addLayout(btns)
        self.stack.addWidget(page)

    def _build_progress(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addStretch(1)
        self.step = QLabel()
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        v.addWidget(self.step)
        v.addWidget(self.bar)
        v.addStretch(2)
        self.stack.addWidget(page)

    def _build_done(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        self.done_title = QLabel()
        self.done_title.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.done_tips = QLabel()
        self.done_tips.setWordWrap(True)
        self.done_tips.setObjectName("Muted")
        self.c_launch = QCheckBox()
        self.c_launch.setChecked(not self.opts.get("no_launch"))
        v.addWidget(self.done_title)
        v.addSpacing(8)
        v.addWidget(self.done_tips)
        v.addStretch(1)
        v.addWidget(self.c_launch)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.finish = QPushButton()
        self.finish.setObjectName("Primary")
        self.finish.clicked.connect(self._finish)
        btns.addWidget(self.finish)
        v.addLayout(btns)
        self.stack.addWidget(page)

    def retranslate(self):
        from ..util import format_size
        self.setWindowTitle(_("Instalar {app}").format(app=APP_NAME))
        self.subtitle.setText(_("Versão {v} · gerenciador de downloads").format(v=VERSION))
        self.lang_label.setText(_("Idioma"))
        self.dir_label.setText(_("Instalar em"))
        self.browse.setText(_("Procurar…"))
        self.c_desktop.setText(_("Criar atalho na Área de Trabalho"))
        self.c_start.setText(_("Criar atalho no Menu Iniciar"))
        self.c_auto.setText(_("Iniciar com o Windows (minimizado perto do relógio)"))
        self.c_assoc.setText(_("Abrir links magnet e arquivos .torrent com o Scarlet DM"))
        self.cancel.setText(_("Cancelar"))
        self.go.setText(_("Instalar"))
        self.done_title.setText(_("Pronto! O Scarlet DM foi instalado."))
        self.done_tips.setText(
            _("Para fixar na barra de tarefas: com o Scarlet aberto, clique com o botão direito no ícone dele na "
              "barra de tarefas → “Fixar na barra de tarefas” (o Windows não deixa programas fazerem isso sozinhos).")
            + "\n\n" +
            _("Para baixar direto do navegador (Chrome, Edge, Brave, Opera, Vivaldi ou Firefox), instale a "
              "extensão: Preferências › Navegador."))
        self.c_launch.setText(_("Abrir o Scarlet DM agora"))
        self.finish.setText(_("Concluir"))
        self.space.setText(_("Espaço necessário: {n}").format(n=format_size(self.need)))

    def _lang_changed(self):
        i18n.set_language(self.lang.currentData())
        self.retranslate()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, _("Escolher pasta"), self.dir.text())
        if d:
            self.dir.setText(pick_target(d))

    # ---------------------------------------------------------- instalação
    def start_install(self):
        self.target = os.path.normpath(self.dir.text().strip() or install.default_dir())
        if not close_running(self, self.target):
            return
        self.stack.setCurrentIndex(1)
        self.go.setEnabled(False)
        choices = {"desktop": self.c_desktop.isChecked(), "startmenu": self.c_start.isChecked(),
                   "autostart": self.c_auto.isChecked(), "assoc": self.c_assoc.isChecked(),
                   "lang": self.lang.currentData()}
        threading.Thread(target=self._run, args=(self.target, choices), daemon=True).start()

    def _run(self, target, choices):
        w = self.worker
        try:
            do_install(self.payload, target, choices, lambda pct, txt: w.progress.emit(pct, txt))
            w.finished.emit("")
        except Exception as e:     # mostra o erro em vez de fechar calado
            w.finished.emit(f"{type(e).__name__}: {e}")

    def _on_progress(self, pct, txt):
        self.bar.setValue(pct)
        self.step.setText(txt)

    def _on_finished(self, err):
        if err:
            QMessageBox.critical(self, APP_NAME, _("Não foi possível instalar:\n{erro}").format(erro=err))
            self.stack.setCurrentIndex(0)
            self.go.setEnabled(True)
            return
        self.stack.setCurrentIndex(2)

    def _finish(self):
        if self.c_launch.isChecked():
            install.launch(os.path.join(self.target, install.EXE_NAME))
        self.accept()


def pick_target(d):
    """Nunca espalha os arquivos numa pasta que já tem outras coisas: cria a subpasta "Scarlet DM"."""
    d = os.path.normpath(d)
    if os.path.isfile(os.path.join(d, install.EXE_NAME)) or os.path.basename(d).lower() == APP_NAME.lower():
        return d
    try:
        empty = not os.listdir(d)
    except OSError:
        empty = True
    return d if empty else os.path.join(d, APP_NAME)


def do_install(payload, target, choices, progress=lambda pct, txt: None):
    """Instala (ou atualiza) o app em target. Também é o caminho do modo silencioso."""
    from .. import autostart
    target = os.path.normpath(target)
    exe = os.path.join(target, install.EXE_NAME)
    os.makedirs(target, exist_ok=True)
    progress(2, _("Preparando…"))
    with zipfile.ZipFile(payload) as z:
        infos = z.infolist()
        total = sum(i.file_size for i in infos) or 1
        tops = set()
        if os.path.isfile(exe):                               # atualização: tira as bibliotecas antigas
            for name in ("_internal", "extension", "extension-firefox"):
                p = os.path.join(target, name)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
        done = 0
        root = target + os.sep
        for i in infos:
            dest = os.path.normpath(os.path.join(target, i.filename))
            if not dest.startswith(root):
                continue                                       # zip malicioso tentando sair da pasta
            tops.add(os.path.relpath(dest, target).split(os.sep)[0])
            if i.is_dir():
                os.makedirs(dest, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(i) as src, open(dest, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    progress(5 + int(done * 85 / total), _("Copiando arquivos… {p}%").format(p=int(done * 100 / total)))
    with open(os.path.join(target, install.MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"version": VERSION, "entries": sorted(tops)}, f, indent=1)
    progress(92, _("Criando atalhos…"))
    lnks = install.shortcut_paths()
    for key in ("desktop", "startmenu"):
        if choices.get(key):
            install.create_shortcut(lnks[key], exe)
        elif os.path.isfile(lnks[key]):
            try:
                os.remove(lnks[key])
            except OSError:
                pass
    progress(96, _("Registrando…"))
    install.register_uninstall(target, total)
    autostart.set_enabled(bool(choices.get("autostart")), exe)
    if choices.get("assoc"):
        autostart.register_handlers(exe)
    install.save_settings({"language": choices.get("lang") or i18n.current(), "welcome_done": True})
    progress(100, _("Concluído"))


# ====================================================================== desinstalador
class UninstallDialog(QDialog):
    def __init__(self, install_dir):
        super().__init__()
        self.install_dir = install_dir
        self.setWindowTitle(_("Desinstalar {app}").format(app=APP_NAME))
        self.setMinimumWidth(540)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 18)
        hdr, _sub = header(_("Versão {v}").format(v=VERSION))
        v.addLayout(hdr)
        v.addSpacing(10)
        q = QLabel(_("Remover o Scarlet DM deste computador?"))
        q.setStyleSheet("font-size: 15px; font-weight: 600;")
        v.addWidget(q)
        self.c_data = QCheckBox(_("Apagar também a lista de downloads, as configurações e os componentes de vídeo"))
        v.addWidget(self.c_data)
        note = QLabel(_("Os arquivos que você baixou não são apagados."))
        note.setObjectName("Muted")
        v.addWidget(note)
        v.addSpacing(10)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(_("Cancelar"))
        cancel.clicked.connect(self.reject)
        go = QPushButton(_("Desinstalar"))
        go.setObjectName("Primary")
        go.clicked.connect(self._go)
        btns.addWidget(cancel)
        btns.addWidget(go)
        v.addLayout(btns)
        QTimer.singleShot(0, lambda: theme.apply_dark_titlebar(self))

    def _go(self):
        if not close_running(self, self.install_dir):
            return
        install.uninstall(self.install_dir, remove_data=self.c_data.isChecked())
        QMessageBox.information(self, APP_NAME, _("O Scarlet DM foi removido."))
        self.accept()


def run_uninstall(args):
    """ScarletDM.exe --uninstall [--silent [--remove-data]]"""
    from PySide6.QtWidgets import QApplication
    if not getattr(sys, "frozen", False):
        print("A desinstalação só vale para a versão instalada (ScarletDM.exe).")
        return 1
    install_dir = os.path.dirname(sys.executable)
    if "--silent" in args:
        running = install.running_instances(install_dir)
        for _pid, path in running:
            install.ask_to_quit(path)
        if not install.wait_closed([p for p, _x in running], 10):
            for pid, _path in install.running_instances(install_dir):
                install.terminate(pid)
        install.uninstall(install_dir, remove_data="--remove-data" in args)
        return 0
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(theme.app_icon())
    i18n.install_qt_translator(app)
    UninstallDialog(install_dir).exec()
    return 0
