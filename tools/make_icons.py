"""Gera os ícones a partir do desenho da logo (scarlet/ui/theme.py: paint_logo).

- extension/icons/{16,32,48,128}.png
- assets/app.ico (vários tamanhos dentro do mesmo .ico: 16…256) e assets/app.png (512)
- assets/app.icns (macOS: 16…1024) e assets/scarletdm.png (256, ícone do AppImage/.desktop no Linux)
- installer/wizard*.bmp (arte do instalador do Inno Setup, 100% e 250% de escala)
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from scarlet.ui.theme import paint_logo  # noqa: E402


def render(size):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_logo(p, float(size))
    p.end()
    return img


def png_bytes(img):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path, sizes):
    """ICO com uma imagem PNG por tamanho (formato aceito desde o Windows Vista)."""
    images = [(s, png_bytes(render(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def write_icns(path):
    """ICNS com PNGs (formato aceito desde o macOS 10.7): ic04 16, ic05 32, ic07 128, ic08 256, ic09 512, ic10 1024."""
    chunks = b""
    for kind, size in ((b"ic04", 16), (b"ic05", 32), (b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
        data = png_bytes(render(size))
        chunks += kind + struct.pack(">I", len(data) + 8) + data
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)


def wizard_art(w, h, logo_frac):
    """Painel escuro com brilho vermelho e o logo no centro (formato BMP que o Inno Setup lê)."""
    from PySide6.QtGui import QColor, QRadialGradient
    from PySide6.QtCore import QPointF
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#0a0a0c"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QRadialGradient(QPointF(w / 2, h * 0.42), max(w, h) * 0.55)
    g.setColorAt(0, QColor(227, 34, 47, 110))
    g.setColorAt(1, QColor(10, 10, 12, 0))
    p.fillRect(0, 0, w, h, g)
    s = int(min(w, h) * logo_frac)
    logo = render(s)
    p.drawImage(int((w - s) / 2), int(h * 0.42 - s / 2), logo)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    ext = os.path.join(ROOT, "extension", "icons")
    os.makedirs(ext, exist_ok=True)
    for size in (16, 32, 48, 128):
        render(size).save(os.path.join(ext, f"{size}.png"))
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)
    write_ico(os.path.join(assets, "app.ico"), (16, 20, 24, 32, 40, 48, 64, 96, 128, 256))
    render(512).save(os.path.join(assets, "app.png"))
    write_icns(os.path.join(assets, "app.icns"))
    render(256).save(os.path.join(assets, "scarletdm.png"))
    inst = os.path.join(ROOT, "installer")
    wizard_art(164, 314, 0.62).save(os.path.join(inst, "wizard.bmp"))
    wizard_art(410, 797, 0.62).save(os.path.join(inst, "wizard-250.bmp"))
    wizard_art(55, 55, 0.9).save(os.path.join(inst, "wizard-small.bmp"))
    wizard_art(138, 138, 0.9).save(os.path.join(inst, "wizard-small-250.bmp"))
    print("ícones gerados em", ext, "e", assets)
