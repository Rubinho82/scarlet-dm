"""Converter depois de baixar: MP3, MP4 e comprimir, com pausa no meio e nomes sem sobrescrever.

Gera o vídeo de teste com o ffmpeg do PATH. Uso: python tests/test_convert.py .
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from scarlet.engine.manager import Manager  # noqa: E402
from scarlet.engine.task import COMPLETED, PAUSED  # noqa: E402
from scarlet.settings import Settings  # noqa: E402

ff, probe = shutil.which("ffmpeg"), shutil.which("ffprobe")
if not ff or not probe:
    print("ffmpeg/ffprobe não estão no PATH; pulando")
    sys.exit(0)
work = tempfile.mkdtemp(prefix="sdm-conv-")
src = os.path.join(work, "Meu Vídeo.mp4")
subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=12",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest", src], check=True)
st = Settings(os.path.join(work, "s.json"))
st["download_dir"] = work
m = Manager(st, os.path.join(work, "db.json"))
ok = True


def check(c, w):
    global ok
    print(("OK   " if c else "FALHA"), w)
    ok = ok and bool(c)


def info(path):
    out = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_name,width:format=duration",
                          "-of", "json", path], capture_output=True, text=True).stdout
    return json.loads(out)


def wait(t, secs=120):
    end = time.time() + secs
    while time.time() < end and t.status != COMPLETED and t.status != "error":
        time.sleep(0.3)
        m.tick()
    return t.status


# pausar no meio e continuar
t = m.convert(src, "compress")
end = time.time() + 30
while time.time() < end and not (t.progress() or 0) > 0.05:
    time.sleep(0.1)
    m.tick()
m.pause(t)
t.wait(10)
m.tick()
check(t.status == PAUSED and not os.path.exists(t.path), f"pausou no meio ({(t.progress() or 0) * 100:.0f}%), sem arquivo pela metade")
m.start(t)
check(wait(t) == COMPLETED, f"comprimir: {t.status} {t.error}")
i = info(t.path)
v = [s for s in i["streams"] if s.get("width")]
check(v and v[0]["width"] == 1280 and v[0]["codec_name"] == "h264", f"comprimido em H.264 1280px ({t.name})")
check(os.path.getsize(t.path) < os.path.getsize(src), f"ficou menor ({os.path.getsize(t.path) // 1024} KB "
                                                       f"< {os.path.getsize(src) // 1024} KB)")

a = m.convert(src, "mp3")
check(wait(a) == COMPLETED, f"MP3: {a.status} {a.error}")
i = info(a.path)
check(a.name == "Meu Vídeo.mp3" and i["streams"][0]["codec_name"] == "mp3" and abs(float(i["format"]["duration"]) - 12) < 0.5,
      f"MP3 com o áudio inteiro ({a.name})")

b = m.convert(src, "mp4")
check(wait(b) == COMPLETED and b.name == "Meu Vídeo (convertido).mp4", f"MP4: {b.name}")
c = m.convert(src, "mp3")
check(wait(c) == COMPLETED and c.name == "Meu Vídeo (1).mp3", f"não sobrescreve: {c.name}")
check(not [f for f in os.listdir(work) if f.endswith(".sdmconv")], "sem arquivos temporários sobrando")

# arquivo original sumiu -> erro claro
os.rename(src, src + ".x")
d = m.convert(src, "mp3")
check(wait(d) == "error" and "não existe" in d.error, f"original apagado vira erro claro: {d.error!r}")
m.shutdown()
print("RESULTADO:", "OK" if ok else "FALHOU")
sys.exit(0 if ok else 1)
