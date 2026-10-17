"""Autoteste do app (principalmente do .exe empacotado): ScarletDM.exe --selftest [vídeo] [--out arquivo.json]

Confere bibliotecas, traduções, abre a janela principal e, se receber um vídeo, toca alguns segundos contando
quadros. Grava o resultado em JSON (padrão: selftest.json na pasta de dados) e sai com 0 (tudo ok) ou 1.
"""
import json
import os
import sys
import time
import traceback


def run(args):
    out = os.path.join(_data_dir(), "selftest.json")
    if "--out" in args and args.index("--out") + 1 < len(args):
        out = args[args.index("--out") + 1]
    video = next((a for a in args if a not in ("--selftest", "--out", out) and os.path.isfile(a)), "")
    res = {"python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False)), "checks": {}}

    def check(name, fn):
        try:
            res["checks"][name] = {"ok": True, "info": fn()}
        except Exception as e:
            res["checks"][name] = {"ok": False, "info": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    def imports():
        import PySide6
        import requests  # noqa: F401
        import cryptography  # noqa: F401
        from PySide6 import QtMultimedia, QtMultimediaWidgets, QtSvg, QtNetwork  # noqa: F401
        from scarlet.engine.torrent import lt
        return {"pyside6": PySide6.__version__, "libtorrent": bool(lt)}
    check("imports", imports)

    def locales():
        from scarlet import i18n
        sizes = {}
        for code, _name in i18n.LANGUAGES:
            i18n.set_language(code)
            sizes[code] = len(i18n._table)
        i18n.set_language("pt_BR")
        bad = [c for c, n in sizes.items() if c != "pt_BR" and n < 400]
        if bad:
            raise RuntimeError(f"traduções faltando: {bad}")
        return sizes
    check("locales", locales)

    def qt_translations():
        from scarlet import i18n
        i18n.set_language("ja")
        tr = i18n.install_qt_translator(app)
        i18n.set_language("pt_BR")
        if tr is None:
            raise RuntimeError("qtbase_ja.qm não encontrado")
        app.removeTranslator(tr)
        return "ok"
    check("qt_translations", qt_translations)

    def main_window():
        from scarlet.engine.manager import Manager
        from scarlet.settings import Settings
        from scarlet.ui.main_window import MainWindow
        from scarlet.ui.dialogs import SettingsDialog
        st = Settings()
        m = Manager(st)
        w = MainWindow(st, m)
        w.show()
        for _ in range(10):
            app.processEvents()
        d = SettingsDialog(st, w)
        d.show()
        app.processEvents()
        d.close()
        size = (w.width(), w.height())
        w._final_shutdown()
        w.tray.hide()
        w.hide()
        return {"size": size}
    check("main_window", main_window)

    if video:
        def player():
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
            p = QMediaPlayer()
            a = QAudioOutput()
            a.setVolume(0)
            p.setAudioOutput(a)
            sink = QVideoSink()
            p.setVideoSink(sink)
            frames = []
            sink.videoFrameChanged.connect(lambda f: frames.append(1))
            p.setSource(QUrl.fromLocalFile(os.path.abspath(video)))
            p.play()
            end = time.time() + 4
            while time.time() < end and len(frames) < 30:
                app.processEvents()
                time.sleep(0.01)
            err = p.errorString()
            p.stop()
            if not frames:
                raise RuntimeError(f"nenhum quadro de vídeo ({err})")
            return {"frames": len(frames)}
        check("player", player)

    res["ok"] = all(c["ok"] for c in res["checks"].values())
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    QTimer.singleShot(0, app.quit)
    return 0 if res["ok"] else 1


def _data_dir():
    from scarlet.util import app_data_dir
    return app_data_dir()
