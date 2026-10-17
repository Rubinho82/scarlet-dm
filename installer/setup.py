"""Instalador do Scarlet DM (vira ScarletDM-<versão>-Setup.exe com tools/build_installer.py).

Instala só para o usuário atual, sem pedir administrador, em %LOCALAPPDATA%\\Programs\\Scarlet DM.

Opções (para instalação automática/empresas):
  --silent            instala sem janelas
  --dir PASTA         pasta de instalação
  --no-desktop        sem atalho na Área de Trabalho
  --no-startmenu      sem atalho no Menu Iniciar
  --autostart         iniciar com o Windows
  --no-handlers       não associar links magnet/.torrent
  --no-launch         não abrir o app no fim
  --lang CÓDIGO       idioma (pt_BR, en, es, fr, de, it, ru, tr, zh_CN, ja, ko)
  --payload ZIP       (testes) usa este zip em vez do embutido
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # rodando pelo código-fonte: acha o pacote scarlet


def arg_value(args, name, default=""):
    if name in args and args.index(name) + 1 < len(args):
        return args[args.index(name) + 1]
    return default


def main():
    args = sys.argv[1:]
    base = getattr(sys, "_MEIPASS", HERE)
    payload = arg_value(args, "--payload") or os.path.join(base, "payload", "ScarletDM.zip")
    from scarlet import i18n, install
    i18n.set_language(arg_value(args, "--lang") or i18n.system_language())
    opts = {"dir": arg_value(args, "--dir"), "no_desktop": "--no-desktop" in args,
            "no_startmenu": "--no-startmenu" in args, "autostart": "--autostart" in args,
            "no_handlers": "--no-handlers" in args, "no_launch": "--no-launch" in args}
    log = os.path.join(os.environ.get("TEMP") or ".", "ScarletDM-setup.log")

    if "--silent" in args:
        from scarlet.ui.setup_ui import do_install
        try:
            target = os.path.normpath(opts["dir"] or install.installed_dir() or install.default_dir())
            running = install.running_instances(only_dir=target)     # só as que travam os arquivos desta pasta
            for _pid, path in running:
                install.ask_to_quit(path)
            if not install.wait_closed([p for p, _x in running], 10):
                for pid, _path in install.running_instances(only_dir=target):
                    install.terminate(pid)
            do_install(payload, target, {"desktop": not opts["no_desktop"], "startmenu": not opts["no_startmenu"],
                                         "autostart": opts["autostart"], "assoc": not opts["no_handlers"],
                                         "lang": i18n.current()})
            if not opts["no_launch"]:
                install.launch(os.path.join(target, install.EXE_NAME))
            return 0
        except Exception:
            with open(log, "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            return 1

    from PySide6.QtWidgets import QApplication, QMessageBox
    from scarlet.ui import theme
    from scarlet.ui.setup_ui import InstallerWindow
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(theme.app_icon())
    i18n.install_qt_translator(app)
    if not os.path.isfile(payload):
        QMessageBox.critical(None, "Scarlet DM", f"Pacote de instalação não encontrado:\n{payload}")
        return 1
    win = InstallerWindow(payload, opts)
    return 0 if win.exec() else 2


if __name__ == "__main__":
    sys.exit(main())
