"""Relatório de problema: .zip com info/settings/downloads, sem senhas, tokens nem hashes de magnet.

Uso: python tests/test_report.py .
"""
import json, os, sys, tempfile, zipfile
sys.path.insert(0, sys.argv[1])
from scarlet import report
from scarlet.settings import Settings
from scarlet.engine.manager import Manager
w = tempfile.mkdtemp()
st = Settings(os.path.join(w, "s.json")); st["download_dir"] = w
st["remote_password"] = "segredo123"; st["proxy_url"] = "http://user:pw@proxy:8080"
m = Manager(st, os.path.join(w, "db.json"))
t = m.add("https://user:pass@cdn.site.com/arq/video.mp4?token=ABC123&sig=x", start=False)
t.error = "403 em https://cdn.site.com/a?token=ZZZ"
t.logmsg("GET https://cdn.site.com/arq/video.mp4?token=ABC123")
m.add("magnet:?xt=urn:btih:abcdef&dn=Filme", start=False)
z = os.path.join(w, "r.zip")
report.build(z, "deu ruim", st, m, True)
zf = zipfile.ZipFile(z); names = zf.namelist(); print(names)
blob = "".join(zf.read(n).decode("utf-8", "replace") for n in names)
ok = all(s not in blob for s in ("segredo123", "ABC123", "ZZZ", "pass@", "pw@", "abcdef"))
ok = ok and "cdn.site.com/arq/video.mp4" in blob and "deu ruim" in blob and "info.txt" in names
print(zf.read("info.txt").decode())
print(json.dumps(json.loads(zf.read("downloads.json"))[0], ensure_ascii=False)[:400])
print("URL len", len(report.issue_url()))
m.shutdown()
print("RESULTADO:", "OK" if ok else "FALHOU"); os._exit(0 if ok else 1)
