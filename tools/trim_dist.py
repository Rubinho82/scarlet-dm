"""Tira do pacote do PyInstaller as partes do Qt que o Scarlet DM não usa (~45 MB a menos para baixar).

O PyInstaller copia o plugin de teclado virtual (que puxa Qt Quick/QML/OpenGL), o leitor de PDF, o OpenGL por
software e as traduções de todos os módulos do Qt. Nada disso é usado: a interface é Qt Widgets e o player de
vídeo desenha com Direct3D. Depois de rodar, teste com:  ScarletDM.exe --selftest

Uso: python tools/trim_dist.py dist\\ScarletDM
"""
import glob
import os
import sys

UNUSED = [
    "opengl32sw.dll", "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll", "Qt6QmlWorkerScript.dll",
    "Qt6OpenGL.dll", "Qt6Pdf.dll", "Qt6VirtualKeyboard.dll",
    "plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll", "plugins/imageformats/qpdf.dll",
    "plugins/platforms/qdirect2d.dll", "plugins/platforms/qminimal.dll", "plugins/platforms/qoffscreen.dll",
    "plugins/generic/qtuiotouchplugin.dll",
]
# traduções do Qt: só as dos botões/diálogos padrão (qtbase) nos idiomas do app
KEEP_QM = {f"qtbase_{c}.qm" for c in ("pt_BR", "es", "fr", "de", "it", "ru", "tr", "zh_CN", "ja", "ko")}


def main(dist):
    qt = os.path.join(dist, "_internal", "PySide6")
    if not os.path.isdir(qt):
        print("pasta do PySide6 não encontrada:", qt)
        return 1
    freed = 0
    for rel in UNUSED:
        p = os.path.join(qt, *rel.split("/"))
        if os.path.isfile(p):
            freed += os.path.getsize(p)
            os.remove(p)
    for p in glob.glob(os.path.join(qt, "translations", "*.qm")):
        if os.path.basename(p) not in KEEP_QM:
            freed += os.path.getsize(p)
            os.remove(p)
    print(f"removidos {freed / 1048576:.1f} MB que o app não usa")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "ScarletDM")))
