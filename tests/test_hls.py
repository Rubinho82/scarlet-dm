"""Testa o HlsTask com streams locais: AES-128 + mestre com áudio separado + detecção por Content-Type."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, sys.argv[1])
from scarlet.settings import Settings  # noqa: E402
from scarlet.engine.manager import Manager  # noqa: E402
from scarlet.engine.task import COMPLETED, ERROR  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hls")


class H(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/stream":      # link sem .m3u8 no nome
            body = open(os.path.join(ROOT, "multi", "master.m3u8"), "rb").read()
            body = body.replace(b"v0/", b"/multi/v0/").replace(b"v1/", b"/multi/v1/").replace(b"v2/", b"/multi/v2/")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


srv = ThreadingHTTPServer(("127.0.0.1", 47399), partial(H, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:47399"

work = tempfile.mkdtemp(prefix="sdm-hls-")
st = Settings(os.path.join(work, "s.json"))
st["download_dir"] = work
m = Manager(st, os.path.join(work, "db.json"))


def wait(t, timeout=60):
    end = time.time() + timeout
    while time.time() < end and t.status not in (COMPLETED, ERROR):
        m.tick()
        # a conversão http->hls troca o objeto da tarefa
        t = next((x for x in m.tasks if x.id == t.id), t)
        time.sleep(0.2)
    return t


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width:format=duration",
                          "-of", "json", path], capture_output=True, text=True).stdout
    j = json.loads(out)
    return [s["codec_type"] + (f"{s.get('width')}" if s.get("width") else "") for s in j["streams"]], \
        float(j["format"]["duration"])


ok_all = True
for label, url, want_w, want_dur in [
    ("AES-128 + áudio muxado", B + "/enc/index.m3u8", 640, 12),
    ("mestre fMP4 + áudio separado", B + "/multi/master.m3u8", 640, 10),
    ("sem .m3u8 (Content-Type)", B + "/stream", 640, 10),
]:
    t = m.add(url)
    t = wait(t)
    ok = t.status == COMPLETED
    info = ""
    if ok:
        streams, dur = probe(t.path)
        info = f"{streams} {dur:.1f}s {t.variant_info}"
        ok = f"video{want_w}" in streams and "audio" in streams and abs(dur - want_dur) < 1.5
    print(f"[{'OK' if ok else 'FALHOU'}] {label}: {t.kind} {t.status} {t.filename} {info} {t.error}")
    if not ok:
        for _, msg in list(t.log)[-10:]:
            print("    ", msg)
    ok_all &= ok

print("sobrou pasta temporária?", [d for d in os.listdir(work) if d.endswith(".sdm-hls")])
srv.shutdown()
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok_all else 1)
