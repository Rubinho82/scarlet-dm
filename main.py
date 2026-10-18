"""Scarlet DM — gerenciador de downloads.

Uso:
    python main.py                  abre a janela
    python main.py --tray           inicia minimizado na bandeja
    python main.py <link> [...]     abre (ou reaproveita a instância aberta) já com os links
    python main.py arquivo.torrent  idem para torrents
    python main.py --quit           fecha a instância aberta (usado pelo instalador)
    python main.py --selftest [vídeo] [--out resultado.json]   autoteste (bibliotecas, traduções, janela, player)
    ScarletDM.exe --uninstall [--silent [--remove-data]]       desinstala (instalador próprio)
    ScarletDM.exe --setup-done LANG [--autostart] [--handlers]  usado pelo instalador do Inno Setup
    ScarletDM.exe --unregister                                 usado pelo desinstalador do Inno Setup
"""
import json
import os
import sys

if sys.platform == "win32" and not getattr(sys, "frozen", False):
    # Rodando pelo python.exe: ID próprio para a barra de tarefas mostrar o ícone do Scarlet, não o do Python.
    # No .exe não precisa (e atrapalharia: o atalho fixado na barra viraria um ícone separado da janela).
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ScarletDM.App")
    except Exception:
        pass

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from scarlet import APP_ID, APP_NAME
from scarlet.engine.manager import Manager
from scarlet.settings import Settings
from scarlet.ui.main_window import MainWindow
from scarlet.ui.theme import app_icon, apply_theme, palette, stylesheet

def _server_name():
    """Uma instância por usuário e por pasta de dados (o modo portátil/testes com outro APPDATA não se misturam)."""
    import hashlib
    from scarlet.util import app_data_dir
    tag = hashlib.sha1(os.path.normcase(app_data_dir()).encode("utf-8")).hexdigest()[:8]
    return f"{APP_ID}-{os.environ.get('USERNAME', 'user')}-{tag}"


SERVER_NAME = _server_name()


def _running():
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    ok = sock.waitForConnected(300)
    sock.abort()
    return ok


def send_to_running(args):
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write(QByteArray(json.dumps({"args": args}).encode("utf-8")))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main():
    args = sys.argv[1:]
    from scarlet.report import install_crash_log
    install_crash_log()          # erros inesperados vão para crash.log (entra no "Relatar problema")
    if "--selftest" in args:
        from scarlet.selftest import run
        return run(args)
    if "--setup-done" in args:          # chamado pelo instalador (Inno Setup) no fim da instalação
        from scarlet import autostart, install
        i = args.index("--setup-done")
        lang = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
        upd = {"welcome_done": True}
        if lang:
            upd["language"] = lang
        install.save_settings(upd)
        try:
            autostart.set_enabled("--autostart" in args)
            if "--handlers" in args:
                autostart.register_handlers()
        except OSError:
            pass
        return 0
    if "--unregister" in args:          # chamado pelo desinstalador: tira "iniciar com o Windows" e as associações
        from scarlet import autostart
        try:
            autostart.set_enabled(False)
            autostart.unregister_handlers(sys.executable)
        except OSError:
            pass
        return 0
    if "--uninstall" in args:
        from scarlet.i18n import set_language, system_language
        set_language(Settings().get("language") or system_language())
        from scarlet.ui.setup_ui import run_uninstall
        return run_uninstall(args)
    settings = Settings()
    from scarlet.i18n import set_language, system_language
    set_language(settings.get("language") or system_language())
    scale = int(settings.get("ui_scale", 100) or 100)
    if scale != 100 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{scale / 100:.2f}"
        os.environ["SCARLETDM_SCALE_SET"] = "1"
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    from scarlet.i18n import install_qt_translator
    qt_tr = install_qt_translator(app)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    if "--restarted" in args:            # reinício pelas Preferências: espera a instância antiga fechar
        import time
        args = [a for a in args if a != "--restarted"]
        end = time.time() + 30
        while time.time() < end and _running():
            time.sleep(0.25)
    if send_to_running(args or ["--show"]) or "--quit" in args:
        return 0

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    apply_theme(settings.get("theme", "dark"), settings.get("accent", "red"))
    app.setPalette(palette())
    app.setStyleSheet(stylesheet())

    if not settings.get("welcome_done") and "--tray" not in args:
        from scarlet.ui.welcome import WelcomeDialog
        before = settings.get("language")
        WelcomeDialog(settings).exec()
        if settings.get("language") != before:         # idioma escolhido agora vale para tudo já nesta abertura
            set_language(settings["language"])
            if qt_tr is not None:
                app.removeTranslator(qt_tr)
            qt_tr = install_qt_translator(app)

    manager = Manager(settings)
    manager.load()
    win = MainWindow(settings, manager)

    def on_conn():
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read():
            raw = bytes(sock.readAll()).decode("utf-8", "replace")
            try:
                incoming = json.loads(raw).get("args", [])
            except ValueError:
                incoming = []
            if "--quit" in incoming:
                win.quit_app()
                return
            win.handle_args([a for a in incoming if a != "--show"] or [])
        sock.readyRead.connect(read)
    server.newConnection.connect(on_conn)

    app.aboutToQuit.connect(win._final_shutdown)
    if not ("--tray" in args and win.tray.isVisible()):
        win.show()
    else:
        from PySide6.QtCore import QTimer
        from scarlet.util import trim_memory
        QTimer.singleShot(3000, trim_memory)     # iniciou escondido: devolve a memória ao Windows
    rest = [a for a in args if a != "--tray"]
    if rest:
        win.handle_args(rest)
    if sys.platform == "darwin":
        # no macOS, links magnet e arquivos .torrent chegam como evento (não como argumento)
        from PySide6.QtCore import QEvent, QObject

        class _OpenFiles(QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.Type.FileOpen:
                    url = ev.url()
                    target = ev.file() or (url.toString() if url.isValid() else "")
                    if target:
                        win.handle_args([target])
                    return True
                return False

        app._open_files = _OpenFiles(app)
        app.installEventFilter(app._open_files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
