"""Limite por download: padrão das Preferências e limite próprio de um download (motor HTTP real).

Uso: python tests/test_speed_cap.py .
"""
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from scarlet.engine.manager import Manager  # noqa: E402
from scarlet.settings import Settings  # noqa: E402

SIZE = 12 * 1024 * 1024
DATA = os.urandom(SIZE)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        start = int(m.group(1)) if m else 0
        end = int(m.group(2)) if m and m.group(2) else SIZE - 1
        self.send_response(206 if m else 200)
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{SIZE}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        try:
            self.wfile.write(DATA[start:end + 1])
        except OSError:
            pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.daemon_threads = True
srv.handle_error = lambda request, client_address: None   # conexões cortadas ao pausar não são erro
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
work = tempfile.mkdtemp(prefix="sdm-cap-")
st = Settings(os.path.join(work, "s.json"))
st["download_dir"] = work
st["per_download_limit_enabled"] = True
st["per_download_limit"] = 2 * 1024 * 1024        # padrão: 2 MB/s por download
st["connections"] = 8
st["max_active"] = 3
m = Manager(st, os.path.join(work, "db.json"))
m.apply_limits()
a = m.add(base + "/padrao.bin", start=False)
b = m.add(base + "/proprio.bin", start=False)
m.set_task_cap(b, 1024 * 1024)                    # só este: 1 MB/s
m.start(a)
m.start(b)
t0 = time.time()
while time.time() - t0 < 6:
    time.sleep(0.5)
    m.tick()
el = time.time() - t0
ra, rb = a.done / el / 1048576, b.done / el / 1048576
m.pause(a)
m.pause(b)
print(f"padrão (2 MB/s): {ra:.2f} MB/s | limite próprio (1 MB/s): {rb:.2f} MB/s")
ok = 1.5 <= ra <= 2.5 and 0.7 <= rb <= 1.3
m.set_task_cap(b, 0)                              # tira o limite próprio -> volta ao padrão
ok = ok and m.task_rate(b) == 2 * 1024 * 1024 and "speed_cap" not in b.options
st["per_download_limit_enabled"] = False          # Preferência desligada -> sem limite
ok = ok and m.task_rate(a) == 0
m.shutdown()
print("RESULTADO:", "OK" if ok else "FALHOU")
os._exit(0 if ok else 1)
