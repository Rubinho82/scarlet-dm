"""Traduções. As chaves são os textos em português; cada idioma é um JSON em scarlet/locales/<código>.json.

Uso:  from scarlet.i18n import _      ...  _("Baixando")   /   _("{n} links").format(n=3)
"""
import json
import os
import sys

LANGUAGES = [
    ("pt_BR", "Português (Brasil)"), ("en", "English"), ("es", "Español"), ("fr", "Français"),
    ("de", "Deutsch"), ("it", "Italiano"), ("ru", "Русский"), ("tr", "Türkçe"),
    ("zh_CN", "简体中文"), ("ja", "日本語"), ("ko", "한국어"),
]
CODES = {c for c, _n in LANGUAGES}

_table = {}
_lang = "pt_BR"


def locales_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")


def system_language():
    """Idioma do sistema mapeado para um dos suportados (padrão: inglês)."""
    code = ""
    if os.name == "nt":
        try:
            import ctypes
            import locale
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            code = locale.windows_locale.get(lcid, "")
        except Exception:
            code = ""
    else:
        code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
        if (not code or code.startswith(("C", "POSIX"))) and sys.platform == "darwin":
            try:   # apps abertos pelo Finder não recebem LANG: pergunta ao macOS
                import subprocess
                out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                     text=True, timeout=5).stdout
                code = out.replace("(", "").replace('"', "").split(",")[0].strip()
            except Exception:
                code = ""
    code = code.replace("-", "_")
    if code.startswith("pt"):
        return "pt_BR"
    if code.startswith("zh"):
        return "zh_CN"
    base = code.split("_")[0]
    return base if base in CODES else "en"


def set_language(code):
    global _table, _lang
    if code not in CODES:
        code = "en"
    _lang = code
    _table = {}
    if code == "pt_BR":
        return
    try:
        with open(os.path.join(locales_dir(), code + ".json"), encoding="utf-8") as f:
            _table = json.load(f)
    except (OSError, ValueError):
        _table = {}


def current():
    return _lang


def _(text):
    return _table.get(text) or text


def install_qt_translator(app):
    """Traduz os textos do próprio Qt (botões Sim/Não/Cancelar, janelas de abrir arquivo…)."""
    if _lang == "en":
        return None
    from PySide6.QtCore import QLibraryInfo, QTranslator
    tr = QTranslator(app)
    if tr.load(f"qtbase_{_lang}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)
        return tr
    return None
