"""Servidor HTTP local (127.0.0.1) que recebe links da extensão do navegador.

Segurança: só aceita requisições sem Origin ou vindas de extensões (chrome-extension://, moz-extension://)
e exige o cabeçalho X-Scarlet-Client. Cabeçalho próprio obriga o navegador a fazer preflight CORS,
que é recusado para sites comuns — então uma página qualquer não consegue enfileirar downloads.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler

from PySide6.QtCore import QObject, Signal

from . import APP_NAME, VERSION
from .util import LocalHTTPServer

ALLOWED_ORIGINS = ("chrome-extension://", "moz-extension://", "extension://", "safari-web-extension://")
URL_PREFIXES = ("http://", "https://", "ftp://", "magnet:?")


class ApiBridge(QObject):
    received = Signal(dict)


class ApiServer:
    def __init__(self, bridge):
        self.bridge = bridge
        self.httpd = None
        self.thread = None
        self.port = None
        self.error = ""

    def running(self):
        return self.httpd is not None

    def start(self, port):
        self.stop()
        bridge = self.bridge

        class Handler(BaseHTTPRequestHandler):
            server_version = "ScarletDM"

            def log_message(self, *a):
                pass

            def _origin(self):
                return self.headers.get("Origin") or ""

            def _origin_ok(self):
                o = self._origin()
                return not o or o.startswith(ALLOWED_ORIGINS)

            def _cors(self):
                o = self._origin()
                if o and o.startswith(ALLOWED_ORIGINS):
                    self.send_header("Access-Control-Allow-Origin", o)
                    self.send_header("Vary", "Origin")

            def _json(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                if not self._origin_ok():
                    return self._json(403, {"error": "origem não permitida"})
                self.send_response(204)
                self._cors()
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Scarlet-Client")
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                if not self._origin_ok():
                    return self._json(403, {"error": "origem não permitida"})
                if self.path.split("?")[0] == "/ping":
                    return self._json(200, {"app": APP_NAME, "version": VERSION})
                return self._json(404, {"error": "não encontrado"})

            def do_POST(self):
                if not self._origin_ok() or not self.headers.get("X-Scarlet-Client"):
                    return self._json(403, {"error": "não autorizado"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = 0
                if n > 4_000_000:
                    return self._json(413, {"error": "grande demais"})
                try:
                    data = json.loads(self.rfile.read(n) or b"{}")
                    if not isinstance(data, dict):
                        raise ValueError
                except ValueError:
                    return self._json(400, {"error": "json inválido"})
                path = self.path.split("?")[0]
                if path == "/show":
                    bridge.received.emit({"show": True})
                    return self._json(200, {"ok": True})
                if path != "/add":
                    return self._json(404, {"error": "não encontrado"})
                urls = [u.strip() for u in data.get("urls", []) if isinstance(u, str)
                        and u.strip().lower().startswith(URL_PREFIXES)][:1000]
                if not urls:
                    return self._json(400, {"error": "nenhum link válido"})

                def s(key, limit=8192):
                    v = data.get(key)
                    return v[:limit] if isinstance(v, str) else ""

                payload = {
                    "urls": urls, "referer": s("referer"), "cookies": s("cookies", 32768),
                    "user_agent": s("userAgent", 1024), "filename": s("filename", 512), "title": s("title", 512),
                    "kind": data.get("kind") if data.get("kind") in ("hls", "media") else "",
                    "silent": bool(data.get("silent")),
                }
                bridge.received.emit(payload)
                return self._json(200, {"ok": True, "count": len(urls)})

        try:
            self.httpd = LocalHTTPServer(("127.0.0.1", int(port)), Handler)
        except OSError as e:
            self.httpd = None
            self.error = str(e)
            return False
        self.httpd.daemon_threads = True
        self.port = int(port)
        self.error = ""
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="api", daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
        self.httpd = None
