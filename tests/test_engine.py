"""Teste do motor do Scarlet DM contra um servidor HTTP local (Range, sem Range, chunked)."""
import hashlib
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, sys.argv[1])
from scarlet.settings import Settings  # noqa: E402
from scarlet.engine.manager import Manager  # noqa: E402
from scarlet.engine.task import COMPLETED, ERROR, PAUSED  # noqa: E402

DATA = os.urandom(24 * 1024 * 1024 + 12345)
SHA = hashlib.sha256(DATA).hexdigest()
CONNS = {"max": 0, "now": 0}
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        with LOCK:
            CONNS["now"] += 1
            CONNS["max"] = max(CONNS["max"], CONNS["now"])
        try:
            self._serve()
        except (ConnectionError, OSError):
            pass
        finally:
            with LOCK:
                CONNS["now"] -= 1

    def _serve(self):
        mode = self.path.strip("/").split("/")[0]
        rng = self.headers.get("Range")
        start = 0
        if mode == "range" and rng:
            m = re.match(r"bytes=(\d+)-", rng)
            start = int(m.group(1))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
            self.send_header("Content-Length", str(len(DATA) - start))
            self.send_header("ETag", '"abc123"')
            self.send_header("Accept-Ranges", "bytes")
        else:
            self.send_response(200)
            if mode != "chunked":
                self.send_header("Content-Length", str(len(DATA)))
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", 'attachment; filename="arquivo teste çã.bin"')
        if mode == "chunked":
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        pos = start
        while pos < len(DATA):
            block = DATA[pos:pos + 32768]
            if mode == "chunked":
                self.wfile.write(f"{len(block):X}\r\n".encode() + block + b"\r\n")
            else:
                self.wfile.write(block)
            pos += len(block)
            time.sleep(0.004)   # ~8 MB/s por conexão: dá vantagem real a várias conexões
        if mode == "chunked":
            self.wfile.write(b"0\r\n\r\n")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

work = tempfile.mkdtemp(prefix="sdm-test-")
st = Settings(os.path.join(work, "settings.json"))
st["download_dir"] = os.path.join(work, "dl")
st["connections"] = 8
db = os.path.join(work, "db.json")


def run_until(mgr, task, cond, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        mgr.tick()
        if cond(task):
            return True
        time.sleep(0.2)
    return False


def check(task, label):
    ok = task.status == COMPLETED and hashlib.sha256(open(task.path, "rb").read()).hexdigest() == SHA
    print(f"[{'OK' if ok else 'FALHOU'}] {label}: status={task.status} err={task.error!r} arquivo={task.filename}")
    if not ok:
        for _, m in list(task.log)[-15:]:
            print("    ", m)
    return ok


results = []

# 1) download segmentado do zero
m = Manager(st, db)
t0 = time.time()
t = m.add(BASE + "/range/x")
run_until(m, t, lambda t: t.status in (COMPLETED, ERROR))
dt = time.time() - t0
print(f"    conexões simultâneas no servidor (máx): {CONNS['max']}, tempo {dt:.1f}s, "
      f"{len(DATA) / dt / 1e6:.1f} MB/s, seções: {len(t.segments)}")
results.append(check(t, "segmentado 8 conexões") and CONNS["max"] >= 4)

# 2) pausa no meio, fecha o gerenciador, reabre e retoma
CONNS["max"] = 0
m = Manager(st, db)
m.load()
t = m.add(BASE + "/range/y")
run_until(m, t, lambda t: t.done > len(DATA) * 0.4, 60)
done_before = t.done
m.shutdown()                       # simula fechar o app
print(f"    pausado com {done_before / len(DATA):.0%}; reabrindo…")
m2 = Manager(st, db)
m2.load()
t2 = next(x for x in m2.tasks if x.id == t.id)
print(f"    estado recarregado: {t2.status}, {t2.done / len(DATA):.0%}, {len(t2.segments)} seções")
run_until(m2, t2, lambda t: t.status in (COMPLETED, ERROR))
results.append(check(t2, "retomada após reabrir"))

# 3) servidor sem suporte a Range
m3 = Manager(st, db)
t = m3.add(BASE + "/norange/z.bin")
run_until(m3, t, lambda t: t.status in (COMPLETED, ERROR))
results.append(check(t, "sem Range (1 conexão)") and t.resumable is False)

# 4) tamanho desconhecido (chunked)
t = m3.add(BASE + "/chunked/c.bin")
run_until(m3, t, lambda t: t.status in (COMPLETED, ERROR))
results.append(check(t, "tamanho desconhecido (chunked)"))

# 5) limite de velocidade 2 MB/s
st["limit_enabled"] = True
st["speed_limit"] = 2 * 1024 * 1024
m3.apply_limits()
t = m3.add(BASE + "/range/lim")
t0 = time.time()
run_until(m3, t, lambda t: t.done > 6 * 1024 * 1024, 60)
rate = t.done / (time.time() - t0)
m3.pause(t)
print(f"    taxa medida com limite de 2 MB/s: {rate / 1024 / 1024:.2f} MB/s")
results.append(1.5 * 1024 * 1024 < rate < 2.6 * 1024 * 1024)
st["limit_enabled"] = False
m3.apply_limits()

# 6) checksum
t = m3.add(BASE + "/range/cs", options={"checksum": {"algo": "sha256", "value": SHA}})
run_until(m3, t, lambda t: t.status in (COMPLETED, ERROR))
results.append(check(t, "checksum SHA-256") and t.verified is True)
t = m3.add(BASE + "/range/csbad", options={"checksum": {"algo": "md5", "value": "0" * 32}})
run_until(m3, t, lambda t: t.status in (COMPLETED, ERROR))
bad = t.status == ERROR and "Checksum" in t.error
print(f"[{'OK' if bad else 'FALHOU'}] checksum errado detectado: {t.error}")
results.append(bad)

# 7) porta fechada vira erro depois das tentativas
st["retries"] = 1
srv_missing = m3.add("http://127.0.0.1:1/x")
run_until(m3, srv_missing, lambda t: t.status == ERROR, 30)
print(f"[{'OK' if srv_missing.status == ERROR else 'FALHOU'}] porta fechada -> {srv_missing.error}")
results.append(srv_missing.status == ERROR)

print("\nnomes gerados:", sorted(os.listdir(st["download_dir"])))
print(f"\n{sum(results)}/{len(results)} testes passaram")
srv.shutdown()
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if all(results) else 1)
