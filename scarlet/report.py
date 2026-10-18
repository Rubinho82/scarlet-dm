"""Relatório de problema: um .zip com o que ajuda a achar o bug, sem senhas nem cookies.

Conteúdo: info.txt (versão, sistema, componentes), settings.json sem senhas, crash.log (erros inesperados que o
app registrou) e, se a pessoa deixar, os últimos downloads (nome, site, estado, erro e registro), com os links
cortados no caminho (sem "?token=..." etc.).
"""
import json
import os
import platform
import re
import sys
import time
import traceback
import urllib.parse
import zipfile

from . import APP_NAME, VERSION
from .util import app_data_dir

SECRET_KEYS = {"remote_password", "proxy_url", "av_args", "post_cmd_args"}
ISSUES = "https://github.com/Rubinho82/scarlet-dm/issues/new"


def crash_log_path():
    return os.path.join(app_data_dir(), "crash.log")


def install_crash_log():
    """Erros não tratados (inclusive em threads) vão para crash.log, além do comportamento normal."""
    import threading

    def write(kind, exc_type, exc, tb):
        try:
            path = crash_log_path()
            if os.path.isfile(path) and os.path.getsize(path) > 512 * 1024:      # não cresce sem fim
                os.replace(path, path + ".old")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} · {APP_NAME} {VERSION} · {kind}\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except OSError:
            pass

    old_hook = sys.excepthook

    def hook(exc_type, exc, tb):
        write("main", exc_type, exc, tb)
        old_hook(exc_type, exc, tb)

    def thread_hook(args):
        write(f"thread {args.thread.name if args.thread else '?'}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook


def redact_url(url):
    """Mantém site e caminho; tira usuário/senha, ?parâmetros e #fragmento (onde costumam ficar tokens)."""
    if not url:
        return ""
    if url.startswith("magnet:"):
        return "magnet:(…)"
    try:
        p = urllib.parse.urlsplit(url)
        host = p.hostname or ""
        return urllib.parse.urlunsplit((p.scheme, host + (f":{p.port}" if p.port else ""), p.path,
                                        "…" if p.query else "", ""))
    except ValueError:
        return "(link inválido)"


def system_info():
    from .engine import components as comp
    from .updater import install_kind
    lines = [f"{APP_NAME} {VERSION} ({install_kind()})",
             f"Sistema: {platform.platform()} · {platform.machine()}",
             f"Python {platform.python_version()}"]
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        lines.append(f"PySide6 {PySide6.__version__} · Qt {qVersion()}")
    except Exception:
        pass
    try:
        from .engine.torrent import lt
        lines.append(f"libtorrent: {'sim' if lt else 'não'}")
    except Exception:
        pass
    for name, fn in (("Mecanismo de vídeos", comp.ytdlp_version), ("ffmpeg", comp.ffmpeg_version),
                     ("JavaScript", comp.js_version)):
        try:
            lines.append(f"{name}: {fn() or 'não instalado'}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{name}: erro ({e})")
    try:
        from .i18n import current
        lines.append(f"Idioma: {current()}")
    except Exception:
        pass
    return "\n".join(lines)


def _settings_clean(settings):
    out = {}
    for k, v in dict(settings).items():
        if k in SECRET_KEYS and v:
            v = "(oculto)"
        out[k] = v
    return out


def _clean_text(msg):
    return re.sub(r"(?:https?|ftp)://[^\s'\"]+", lambda m: redact_url(m.group(0)), str(msg))


def _tasks_summary(manager, limit=60):
    rows = []
    for t in list(manager.tasks)[-limit:]:
        log = [f"{time.strftime('%H:%M:%S', time.localtime(ts))} {_clean_text(msg)}" for ts, msg in list(t.log)[-40:]]
        rows.append({"tipo": t.kind, "nome": t.name if t.kind != "media" else (t.options.get("title") or "")[:120],
                     "link": redact_url(t.url), "estado": t.status, "erro": _clean_text(t.error), "registro": log})
    return rows


def build(dest, description="", settings=None, manager=None, include_downloads=True):
    """Grava o .zip em dest e devolve o caminho."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("leia-me.txt", f"Relatório do {APP_NAME} {VERSION} gerado em {time.strftime('%Y-%m-%d %H:%M')}\n\n"
                                  f"O que aconteceu (escrito pela pessoa):\n{description.strip() or '(não informado)'}\n")
        z.writestr("info.txt", system_info())
        if settings is not None:
            z.writestr("settings.json", json.dumps(_settings_clean(settings), ensure_ascii=False, indent=2))
        for p in (crash_log_path(), crash_log_path() + ".old"):
            if os.path.isfile(p):
                z.write(p, os.path.basename(p))
        if include_downloads and manager is not None:
            z.writestr("downloads.json", json.dumps(_tasks_summary(manager), ensure_ascii=False, indent=2))
    return dest


def issue_url():
    """Página para abrir um relato no GitHub, já com versão e sistema preenchidos."""
    body = (f"**O que aconteceu?**\n\n\n**O que eu esperava?**\n\n\n**Como repetir o problema?**\n1. \n\n"
            f"---\n{APP_NAME} {VERSION} · {platform.platform()}\n"
            f"(Se puder, anexe o .zip gerado em Menu › Relatar problema.)")
    return ISSUES + "?" + urllib.parse.urlencode({"body": body})
