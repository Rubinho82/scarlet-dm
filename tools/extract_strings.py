"""Lista todas as frases traduzíveis do app (chaves das traduções) em scarlet/locales/_keys.json."""
import ast
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def from_calls():
    keys = []
    for path in sorted(glob.glob(os.path.join(ROOT, "scarlet", "**", "*.py"), recursive=True)):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys.append(node.args[0].value)
    return keys


def from_constants():
    from scarlet.engine.task import STATUS_LABELS
    from scarlet.engine import media_task as mt
    from scarlet.util import CATEGORY_LABELS
    from scarlet.ui.model import FILTERS, COLS
    from scarlet.ui.details import DetailsPanel
    from scarlet.remote import REMOTE_TEXTS
    keys = list(STATUS_LABELS.values()) + list(CATEGORY_LABELS.values()) + [l for _k, l in FILTERS]
    keys += [l for _k, l in DetailsPanel.TECH] + list(REMOTE_TEXTS) + list(COLS)
    for lst in (mt.VIDEO_QUALITIES, mt.FPS_CHOICES, mt.AUDIO_FORMATS, mt.AUDIO_KBPS):
        keys += [l for _k, l in lst]
    return keys


if __name__ == "__main__":
    seen, keys = set(), []
    for k in from_calls() + from_constants():
        if k.strip() and k not in seen:
            seen.add(k)
            keys.append(k)
    out = os.path.join(ROOT, "scarlet", "locales", "_keys.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=0)
    print(len(keys), "frases ->", out)
