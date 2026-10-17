"""Iniciar com o sistema e abrir links magnet/.torrent no Scarlet DM.

Windows: chave Run e HKCU\Software\Classes.  Linux: ~/.config/autostart e um .desktop com x-scheme-handler/magnet.
macOS: LaunchAgent em ~/Library/LaunchAgents; os links ficam declarados no Info.plist do app.
"""
import os
import subprocess
import sys

from . import APP_ID, APP_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
IS_WIN, IS_MAC = os.name == "nt", sys.platform == "darwin"
DESKTOP_ID = "scarletdm.desktop"
MAC_AGENT = os.path.expanduser("~/Library/LaunchAgents/com.scarletdm.app.plist")


def _argv(exe=None):
    """Programa + argumentos para abrir o app (AppImage, .app, executável ou python main.py)."""
    if exe:
        return [exe]
    if os.environ.get("APPIMAGE"):                 # dentro de um AppImage: o arquivo .AppImage é o que fica
        return [os.environ["APPIMAGE"]]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    if IS_WIN and os.path.exists(pyw):
        py = pyw
    return [py, os.path.abspath(sys.argv[0])]


def _desktop_exec(args):
    return " ".join('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"' if (" " in a or '"' in a) else a
                    for a in args)


def _icon_path():
    for c in (os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "assets", "app.png"),
              os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "app.png")):
        if os.path.isfile(c):
            return c
    return "scarletdm"


def _write_desktop(path, args, extra):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["[Desktop Entry]", "Type=Application", f"Name={APP_NAME}", "Comment=Download manager",
             f"Exec={_desktop_exec(args)}", f"Icon={_icon_path()}", "Terminal=false",
             "Categories=Network;FileTransfer;", "StartupWMClass=ScarletDM"] + extra
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _linux_autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", DESKTOP_ID)


def _linux_apps_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "applications", DESKTOP_ID)


def _mac_plist(args):
    items = "".join(f"<string>{a.replace('&', '&amp;').replace('<', '&lt;')}</string>" for a in args)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
            '<key>Label</key><string>com.scarletdm.app</string>'
            f'<key>ProgramArguments</key><array>{items}</array>'
            '<key>RunAtLoad</key><true/><key>ProcessType</key><string>Interactive</string></dict></plist>\n')


def command(exe=None):
    """Comando de inicialização. exe = caminho do ScarletDM.exe instalado (o instalador passa o seu)."""
    if exe:
        return f'"{exe}" --tray'
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    main = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{main}" --tray'


def open_command(exe=None):
    """Comando para abrir arquivos/links no app (sem --tray)."""
    return command(exe).replace(" --tray", "")


def register_handlers(exe=None):
    """Registra o Scarlet DM para links magnet: e arquivos .torrent (só no usuário atual, HKCU).
    Se outro programa já foi escolhido como padrão, o Windows ainda pede confirmação nos Aplicativos padrão."""
    if IS_MAC:
        return          # declarado no Info.plist do .app: o macOS registra sozinho
    if not IS_WIN:
        path = _linux_apps_path()
        _write_desktop(path, _argv(exe) + ["%u"],
                       ["MimeType=x-scheme-handler/magnet;application/x-bittorrent;"])
        for cmd in (["xdg-mime", "default", DESKTOP_ID, "x-scheme-handler/magnet", "application/x-bittorrent"],
                    ["update-desktop-database", os.path.dirname(path)]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
        return
    import winreg
    cmd = f'{open_command(exe)} "%1"'
    icon = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "assets", "app.ico")
    if exe or getattr(sys, "frozen", False):
        icon = (exe or sys.executable) + ",0"

    def setkey(path, values):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{path}", 0, winreg.KEY_SET_VALUE) as k:
            for name, val in values.items():
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)

    setkey("magnet", {"": "URL:Magnet link", "URL Protocol": ""})
    setkey(r"magnet\DefaultIcon", {"": icon})
    setkey(r"magnet\shell\open\command", {"": cmd})
    setkey("ScarletDM.torrent", {"": "Torrent (Scarlet DM)"})
    setkey(r"ScarletDM.torrent\DefaultIcon", {"": icon})
    setkey(r"ScarletDM.torrent\shell\open\command", {"": cmd})
    setkey(r".torrent\OpenWithProgids", {"ScarletDM.torrent": ""})
    setkey(".torrent", {"": "ScarletDM.torrent"})
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)   # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def is_enabled():
    if IS_MAC:
        return os.path.isfile(MAC_AGENT)
    if not IS_WIN:
        return os.path.isfile(_linux_autostart_path())
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
            return True
    except OSError:
        return False


def set_enabled(on, exe=None):
    if not IS_WIN:
        path = MAC_AGENT if IS_MAC else _linux_autostart_path()
        if on:
            if IS_MAC:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(_mac_plist(_argv(exe) + ["--tray"]))
            else:
                _write_desktop(path, _argv(exe) + ["--tray"], ["X-GNOME-Autostart-enabled=true"])
        elif os.path.isfile(path):
            os.remove(path)
        return
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, command(exe))
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except OSError:
                pass


def unregister_handlers(exe):
    """Desfaz register_handlers, mas só o que ainda aponta para este exe (não mexe se outro app assumiu)."""
    if not IS_WIN:
        if not IS_MAC and os.path.isfile(_linux_apps_path()):
            os.remove(_linux_apps_path())
        return
    import winreg

    def points_here(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{path}\shell\open\command") as k:
                return os.path.normcase(exe) in os.path.normcase(winreg.QueryValueEx(k, "")[0])
        except OSError:
            return False

    def delete_tree(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{path}") as k:
                children = []
                while True:
                    try:
                        children.append(winreg.EnumKey(k, len(children)))
                    except OSError:
                        break
            for c in children:
                delete_tree(path + "\\" + c)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{path}")
        except OSError:
            pass

    if points_here("magnet"):
        delete_tree("magnet")
    if points_here("ScarletDM.torrent"):
        delete_tree("ScarletDM.torrent")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.torrent\OpenWithProgids", 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "ScarletDM.torrent")
        except OSError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.torrent", 0,
                                winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                if winreg.QueryValueEx(k, "")[0] == "ScarletDM.torrent":
                    winreg.DeleteValue(k, "")
        except OSError:
            pass
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass
