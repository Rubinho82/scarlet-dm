"""Mostra, para cada idioma, as frases do código que ainda não têm tradução.

Uso: python tools/check_locales.py [idioma]
Frases iguais ao original (nomes próprios, "MP3", "Torrent"…) aparecem como faltando e podem ser ignoradas.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_strings import ROOT, from_calls, from_constants  # noqa: E402


def main(only=None):
    keys = []
    for k in from_calls() + from_constants():
        if k.strip() and k not in keys:
            keys.append(k)
    loc = os.path.join(ROOT, "scarlet", "locales")
    for name in sorted(os.listdir(loc)):
        lang = name[:-5]
        if not name.endswith(".json") or name.startswith("_") or (only and lang != only):
            continue
        table = json.load(open(os.path.join(loc, name), encoding="utf-8"))
        missing = [k for k in keys if k not in table]
        print(f"{lang}: {len(keys) - len(missing)}/{len(keys)} traduzidas")
        for k in missing:
            print("   ", repr(k))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
