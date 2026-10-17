"""Baixa os ícones SVG (Lucide, licença ISC) usados no Linux/macOS, onde não existe a fonte Segoe Fluent Icons.

Uso: python tools/fetch_icons.py      -> scarlet/assets/icons/<nome>.svg (já vem no repositório; só rode para atualizar)
"""
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "0.460.0"
URL = "https://unpkg.com/lucide-static@{v}/icons/{n}.svg"

# nome no app -> nome no Lucide
ICONS = {
    "add": "plus", "play": "play", "pause": "pause", "delete": "trash-2", "folder": "folder", "search": "search",
    "menu": "menu", "settings": "settings", "link": "link", "down": "arrow-down", "up": "arrow-up",
    "refresh": "refresh-cw", "copy": "copy", "close": "x", "paste": "clipboard-paste", "import": "file-input",
    "save": "save", "power": "power", "speed": "gauge", "info": "info", "video": "video", "audio": "music",
    "document": "file-text", "archive": "archive", "program": "app-window", "image": "image", "torrent": "magnet",
    "stream": "radio", "other": "file", "check": "check", "error": "circle-alert", "clock": "clock",
    "globe": "globe", "calendar": "calendar", "chevron": "chevron-down", "open": "external-link",
    "top": "chevrons-up", "bottom": "chevrons-down", "edit": "pencil", "chart": "chart-line",
    "prev": "skip-back", "next": "skip-forward", "volume": "volume-2", "mute": "volume-x",
    "fullscreen": "maximize", "exit_fullscreen": "minimize",
}


def main():
    out = os.path.join(ROOT, "scarlet", "assets", "icons")
    os.makedirs(out, exist_ok=True)
    for name, lucide in ICONS.items():
        with urllib.request.urlopen(URL.format(v=VERSION, n=lucide), timeout=30) as r:
            svg = r.read().decode("utf-8")
        if "<svg" not in svg:
            raise RuntimeError(f"resposta inesperada para {lucide}")
        with open(os.path.join(out, name + ".svg"), "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
    with open(os.path.join(out, "LICENSE.txt"), "w", encoding="utf-8") as f:
        f.write("Icons from Lucide (https://lucide.dev), ISC License.\n"
                "Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT).\n"
                "All other copyright (c) for Lucide are held by Lucide Contributors 2022.\n")
    print(len(ICONS), "ícones em", out)


if __name__ == "__main__":
    main()
