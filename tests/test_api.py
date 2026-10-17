import sys, threading, json, requests
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QCoreApplication, QTimer
from scarlet.api import ApiBridge, ApiServer
app = QCoreApplication([])
got = []
b = ApiBridge(); b.received.connect(got.append)
srv = ApiServer(b); assert srv.start(47388), srv.error
U = "http://127.0.0.1:47388"
res = {}
def run():
    ext = {"Origin": "chrome-extension://abcdef", "X-Scarlet-Client": "extension", "Content-Type": "application/json"}
    res["ping"] = requests.get(U + "/ping", headers={"Origin": "chrome-extension://abcdef"}).json()
    pre = requests.options(U + "/add", headers={"Origin": "chrome-extension://abcdef", "Access-Control-Request-Headers": "x-scarlet-client"})
    res["preflight_ext"] = (pre.status_code, pre.headers.get("Access-Control-Allow-Origin"))
    res["add_ext"] = requests.post(U + "/add", headers=ext, data=json.dumps({"urls": ["https://x.com/a.zip", "javascript:alert(1)"], "referer": "https://x.com/", "cookies": "s=1"})).status_code
    res["preflight_site"] = requests.options(U + "/add", headers={"Origin": "https://site-qualquer.com"}).status_code
    res["add_site"] = requests.post(U + "/add", headers={**ext, "Origin": "https://site-qualquer.com"}, data='{"urls":["https://x.com/b.zip"]}').status_code
    res["add_sem_header"] = requests.post(U + "/add", headers={"Content-Type": "text/plain"}, data='{"urls":["https://x.com/c.zip"]}').status_code
    res['_fim'] = True
threading.Thread(target=run, daemon=True).start()
poll = QTimer(); poll.timeout.connect(lambda: res.get('_fim') and app.quit()); poll.start(200)
app.exec(); srv.stop(); res.pop('_fim', None)
for k, v in res.items(): print(f"{k:16} {v}")
print("recebidos pelo app:", got)
ok = (res["add_ext"] == 200 and res["preflight_site"] == 403 and res["add_site"] == 403 and res["add_sem_header"] == 403
      and len(got) == 1 and got[0]["urls"] == ["https://x.com/a.zip"])
print("RESULTADO:", "OK" if ok else "FALHOU")
