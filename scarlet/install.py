"""Instalação no Windows só para o usuário atual (sem pedir administrador).

Usado pelo instalador (installer/setup.py) e por "ScarletDM.exe --uninstall":
atalhos, entrada em "Aplicativos instalados", fechar instâncias abertas e desinstalar.
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes  # (importa em qualquer sistema; só é usado no Windows)

from . import APP_ID, APP_NAME, VERSION

EXE_NAME = "ScarletDM.exe"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
MANIFEST = "install.json"           # lista do que o instalador colocou na pasta (o desinstalador só apaga isso)
NO_WINDOW = 0x08000000


# ------------------------------------------------------------------ pastas
class _GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        h = text.strip("{}").replace("-", "")
        self.a, self.b, self.c = int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16)
        for i in range(8):
            self.d[i] = int(h[16 + 2 * i:18 + 2 * i], 16)


_FOLDERS = {"desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",     # Área de Trabalho (mesmo se estiver no OneDrive)
            "programs": "A77F5D77-2E2B-44C3-A6A2-ABA601054A51"}    # Menu Iniciar > Programas


def known_folder(name):
    ptr = ctypes.c_wchar_p()
    guid = _GUID(_FOLDERS[name])
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(ptr)) != 0:
        raise OSError(f"pasta {name} não encontrada")
    try:
        return ptr.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ptr)


def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Programs", APP_NAME)


def shortcut_paths():
    return {"desktop": os.path.join(known_folder("desktop"), APP_NAME + ".lnk"),
            "startmenu": os.path.join(known_folder("programs"), APP_NAME + ".lnk")}


# ------------------------------------------------------------------ atalhos
def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def create_shortcut(lnk, target, args="", icon=None, workdir=None, description=APP_NAME):
    """Cria um .lnk (via WScript.Shell; há PowerShell e Windows Script Host em todo Windows 10/11)."""
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    workdir = workdir or os.path.dirname(target)
    icon = icon or target + ",0"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(lnk)});"
          f"$s.TargetPath={_ps_quote(target)};$s.Arguments={_ps_quote(args)};"
          f"$s.WorkingDirectory={_ps_quote(workdir)};$s.IconLocation={_ps_quote(icon)};"
          f"$s.Description={_ps_quote(description)};$s.Save()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       creationflags=NO_WINDOW, timeout=60, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
    if os.path.isfile(lnk):
        return True
    # plano B: VBScript (PowerShell bloqueado por política, por exemplo)
    def vb(s):
        return '"' + str(s).replace('"', '""') + '"'
    script = os.path.join(tempfile.gettempdir(), f"sdm-lnk-{os.getpid()}.vbs")
    with open(script, "w", encoding="utf-16") as f:
        f.write(f'Set s = CreateObject("WScript.Shell").CreateShortcut({vb(lnk)})\r\n'
                f"s.TargetPath = {vb(target)}\r\ns.Arguments = {vb(args)}\r\ns.WorkingDirectory = {vb(workdir)}\r\n"
                f"s.IconLocation = {vb(icon)}\r\ns.Description = {vb(description)}\r\ns.Save\r\n")
    try:
        subprocess.run(["cscript", "//nologo", "//B", script], creationflags=NO_WINDOW, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    return os.path.isfile(lnk)


# ------------------------------------------------------------------ processos abertos
def clean_env():
    """Ambiente para abrir o ScarletDM.exe a partir de outro programa empacotado (o instalador).

    Sem isso, o .exe filho herda variáveis do PyInstaller/Qt do pai (apontando para a pasta temporária dele)."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("_PYI", "_MEIPASS", "QT_", "QML", "PYSIDE"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def launch(exe, *args):
    return subprocess.Popen([exe, *args], env=clean_env(), close_fds=True, cwd=os.path.dirname(exe),
                            creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def running_instances(only_dir=None):
    """[(pid, caminho)] de todos os ScarletDM.exe abertos (opcionalmente só os de uma pasta)."""
    psapi, k32 = ctypes.windll.psapi, ctypes.windll.kernel32
    arr = (wintypes.DWORD * 4096)()
    got = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(got)):
        return []
    out = []
    me = os.getpid()
    for pid in arr[:got.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid or pid == me:
            continue
        h = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                path = buf.value
                if os.path.basename(path).lower() == EXE_NAME.lower():
                    if not only_dir or os.path.normcase(os.path.dirname(path)) == os.path.normcase(only_dir):
                        out.append((pid, path))
        finally:
            k32.CloseHandle(h)
    return out


def ask_to_quit(exe):
    """Pede educadamente para a instância aberta salvar e sair (versão 2.0+ entende --quit)."""
    if os.path.isfile(exe):
        try:
            subprocess.run([exe, "--quit"], creationflags=NO_WINDOW, timeout=15, env=clean_env())
        except (OSError, subprocess.SubprocessError):
            pass


def wait_closed(pids, secs=10):
    end = time.time() + secs
    while time.time() < end:
        alive = {p for p, _ in running_instances()}
        if not any(p in alive for p in pids):
            return True
        time.sleep(0.3)
    return False


def terminate(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)  # PROCESS_TERMINATE | SYNCHRONIZE
    if h:
        try:
            k32.TerminateProcess(h, 1)
            k32.WaitForSingleObject(h, 5000)
        finally:
            k32.CloseHandle(h)


# ------------------------------------------------------------------ registro
def register_uninstall(install_dir, size_bytes):
    import winreg
    exe = os.path.join(install_dir, EXE_NAME)
    values = {
        "DisplayName": APP_NAME, "DisplayVersion": VERSION, "Publisher": APP_NAME,
        "DisplayIcon": exe + ",0", "InstallLocation": install_dir,
        "UninstallString": f'"{exe}" --uninstall', "QuietUninstallString": f'"{exe}" --uninstall --silent',
    }
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name, val in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(size_bytes // 1024))
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "InstallDate", 0, winreg.REG_SZ, time.strftime("%Y%m%d"))


def installed_dir():
    """Pasta da instalação registrada (ou "" se não instalado)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0]
    except OSError:
        return ""


def unregister_uninstall():
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


def save_settings(updates, data_dir=None):
    """Mescla preferências escolhidas no instalador (idioma, iniciar com o Windows…) no settings.json do app."""
    from .util import app_data_dir
    path = os.path.join(data_dir or app_data_dir(), "settings.json")
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.update(updates)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


# ------------------------------------------------------------------ desinstalar
def uninstall(install_dir, remove_data=False, remove_shortcuts=True):
    """Desfaz a instalação. Os arquivos do programa são apagados por um script depois que este processo sair
    (um .exe não consegue apagar a si mesmo enquanto roda)."""
    from . import autostart
    exe = os.path.join(install_dir, EXE_NAME)
    if remove_shortcuts:
        try:
            for lnk in shortcut_paths().values():
                if os.path.isfile(lnk):
                    os.remove(lnk)
        except OSError:
            pass
    try:
        if autostart.is_enabled():
            autostart.set_enabled(False)
    except OSError:
        pass
    autostart.unregister_handlers(exe)
    unregister_uninstall()
    if remove_data:
        from .util import app_data_dir
        _schedule_delete([app_data_dir()])
    entries = []
    try:
        with open(os.path.join(install_dir, MANIFEST), encoding="utf-8") as f:
            entries = json.load(f).get("entries", [])
    except (OSError, ValueError):
        entries = [EXE_NAME, "_internal", "extension", "extension-firefox"]
    _schedule_delete(safe_entries(install_dir, entries + [MANIFEST]), then_rmdir=install_dir)


def safe_entries(install_dir, entries):
    """Só nomes simples dentro da pasta do programa: nada de "..", caminhos absolutos ou subpastas."""
    base = os.path.normcase(os.path.normpath(install_dir))
    out = []
    for e in entries:
        if not isinstance(e, str) or not e or e in (".", "..") or "/" in e or "\\" in e or ":" in e:
            continue
        p = os.path.normpath(os.path.join(install_dir, e))
        if os.path.normcase(os.path.dirname(p)) == base:
            out.append(p)
    return out


def _schedule_delete(paths, then_rmdir=None):
    """Apaga caminhos assim que este processo terminar (PowerShell escondido; aceita qualquer caractere no caminho)."""
    import base64
    q = _ps_quote
    ps = [f"Wait-Process -Id {os.getpid()} -Timeout 120 -ErrorAction SilentlyContinue", "Start-Sleep -Milliseconds 500"]
    for p in paths:
        ps.append(f"Remove-Item -LiteralPath {q(p)} -Recurse -Force -ErrorAction SilentlyContinue")
    if then_rmdir:
        ps.append(f"if ((Test-Path -LiteralPath {q(then_rmdir)}) -and -not (Get-ChildItem -LiteralPath {q(then_rmdir)} -Force)) "
                  f"{{ Remove-Item -LiteralPath {q(then_rmdir)} -Force -ErrorAction SilentlyContinue }}")
    enc = base64.b64encode("; ".join(ps).encode("utf-16-le")).decode("ascii")
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                     creationflags=NO_WINDOW, close_fds=True, cwd=tempfile.gettempdir())
