"""Acesso remoto: página web (celular/outro PC na mesma rede) protegida por senha.

Leitura da lista acontece na thread do servidor; qualquer ação (adicionar, pausar…) é enviada para a
thread da interface por sinal Qt, onde o gerenciador é alterado com segurança.
"""
import hmac
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

from PySide6.QtCore import QObject, Signal

from .engine.task import STATUS_LABELS, ACTIVE_STATES, SEEDING
from .i18n import _
from .util import LocalHTTPServer, format_size, format_speed, format_eta

REMOTE_TEXTS = ("Acesso remoto", "Senha", "Entrar", "Senha incorreta", "Pausar tudo", "Retomar",
                "Cole um link (arquivo, YouTube, magnet…)", "Baixar", "Nenhum download.", "Pausar", "Iniciar")


def localize(page):
    from .i18n import current
    page = page.replace("%LANG%", current().replace("_", "-"))
    for t in REMOTE_TEXTS:
        page = page.replace(t, _(t))
    return page


class RemoteBridge(QObject):
    action = Signal(dict)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


LOGIN_HTML = """<!doctype html><html lang="%LANG%"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Scarlet DM</title>
<style>body{margin:0;background:#0a0a0c;color:#ededf1;font:15px system-ui,Segoe UI,sans-serif;display:grid;
place-items:center;min-height:100vh}form{background:#111114;border:1px solid #26262c;border-radius:12px;padding:28px;
width:min(340px,90vw)}h1{font-size:20px;margin:0 0 4px}p{color:#8d8d97;margin:0 0 18px}input{width:100%;
box-sizing:border-box;padding:11px;border-radius:8px;border:1px solid #26262c;background:#17171b;color:#fff;
font-size:15px}button{margin-top:12px;width:100%;padding:11px;border:0;border-radius:8px;background:#e3222f;
color:#fff;font-weight:600;font-size:15px}.e{color:#ff3d49;margin-top:10px}</style></head><body>
<form method="post" action="/login"><h1>Scarlet DM</h1><p>Acesso remoto</p>
<input type="password" name="password" placeholder="Senha" autofocus>
<button>Entrar</button>%ERR%</form></body></html>"""

APP_HTML = """<!doctype html><html lang="%LANG%"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Scarlet DM</title>
<style>:root{--bg:#0a0a0c;--p:#111114;--p2:#17171b;--b:#26262c;--t:#ededf1;--m:#8d8d97;--a:#e3222f;--ah:#ff3d49}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:14px system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;background:var(--p);border-bottom:1px solid var(--b);padding:12px 16px;display:flex;
gap:10px;align-items:center}header h1{font-size:17px;margin:0;flex:1}#sp{color:var(--ah);font-weight:600}
form{display:flex;gap:8px;padding:12px 16px;border-bottom:1px solid var(--b)}input{flex:1;min-width:0;padding:10px;
border-radius:8px;border:1px solid var(--b);background:var(--p2);color:#fff}button{padding:9px 14px;border:0;
border-radius:8px;background:var(--a);color:#fff;font-weight:600}button.g{background:var(--p2);border:1px solid var(--b)}
.it{padding:12px 16px;border-bottom:1px solid #16161a}.n{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.s{color:var(--m);font-size:12px;margin:4px 0 6px}.bar{height:6px;background:#232329;border-radius:4px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#7d141c,var(--ah))}.row{display:flex;gap:8px;
align-items:center}.row .n{flex:1}.err{color:var(--ah)}.empty{color:var(--m);padding:30px 16px;text-align:center}
</style></head><body><header><h1>Scarlet DM</h1><span id="sp"></span>
<button class="g" onclick="act('','pause_all')">Pausar tudo</button>
<button class="g" onclick="act('','resume_all')">Retomar</button></header>
<form onsubmit="add(event)"><input id="u" placeholder="Cole um link (arquivo, YouTube, magnet…)">
<button>Baixar</button></form><div id="l"></div>
<script>
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function post(p,b){const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json',
'X-Scarlet-Remote':'1'},body:JSON.stringify(b)});if(r.status==401)location.reload();return r}
async function add(e){e.preventDefault();const u=document.getElementById('u');if(!u.value.trim())return;
await post('/api/add',{urls:u.value.split(/\\s+/).filter(Boolean)});u.value='';load()}
async function act(id,a){await post('/api/action',{id,action:a});setTimeout(load,300)}
async function load(){const r=await fetch('/api/tasks');if(r.status==401)return location.reload();
const d=await r.json();document.getElementById('sp').textContent=d.speed?'↓ '+d.speed:'';
const l=document.getElementById('l');if(!d.tasks.length){l.innerHTML='<div class="empty">Nenhum download.</div>';return}
l.innerHTML=d.tasks.map(t=>`<div class="it"><div class="row"><div class="n">${esc(t.name)}</div>
${t.running?`<button class="g" onclick="act('${esc(t.id)}','pause')">Pausar</button>`:
(t.status!='completed'?`<button class="g" onclick="act('${esc(t.id)}','start')">Iniciar</button>`:'')}</div>
<div class="s ${t.status=='error'?'err':''}">${esc(t.label)}${t.speed?' · '+esc(t.speed):''}${t.eta?' · '+esc(t.eta):''}
${t.size?' · '+esc(t.size):''}</div><div class="bar"><i style="width:${(+t.progress||0)*100}%"></i></div></div>`).join('')}
load();setInterval(load,2000);
</script></body></html>"""


class RemoteServer:
    def __init__(self, manager, bridge):
        self.m = manager
        self.bridge = bridge
        self.httpd = None
        self.port = None
        self.error = ""
        self.password = ""
        self._sessions = {}
        self._fails = {}

    def running(self):
        return self.httpd is not None

    def url(self):
        return f"http://{lan_ip()}:{self.port}" if self.running() else ""

    def snapshot(self):
        out = []
        for t in list(self.m.tasks):
            p = t.progress()
            out.append({
                "id": t.id, "name": t.name, "status": t.status,
                "label": (t.error if t.error else _(STATUS_LABELS.get(t.status, t.status))),
                "progress": p if p is not None else 0,
                "speed": format_speed(t.speed) if t.status in ACTIVE_STATES or t.status == SEEDING else "",
                "eta": format_eta(t.eta()) if t.status in ACTIVE_STATES else "",
                "size": format_size(t.total) if t.total > 0 else "",
                "running": t.status in ACTIVE_STATES or t.status in ("queued", SEEDING),
            })
        out.sort(key=lambda x: (not x["running"], x["status"] == "completed"))
        return {"tasks": out[:300], "speed": format_speed(self.m.total_speed())}

    def start(self, port, password):
        self.stop()
        self.password = password
        self._sessions = {}
        srv = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ScarletDM"

            def log_message(self, *a):
                pass

            def _token(self):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "sdm":
                        return v
                return ""

            def _authed(self):
                tok = self._token()
                exp = srv._sessions.get(tok)
                return bool(tok) and exp is not None and exp > time.time()

            def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path.split("?")[0]
                if not self._authed():
                    if path.startswith("/api/"):
                        return self._send(401, "{}", "application/json")
                    return self._send(200, localize(LOGIN_HTML.replace("%ERR%", "")))
                if path == "/api/tasks":
                    return self._send(200, json.dumps(srv.snapshot()), "application/json")
                if path == "/":
                    return self._send(200, localize(APP_HTML))
                return self._send(404, "não encontrado", "text/plain; charset=utf-8")

            def do_POST(self):
                path = self.path.split("?")[0]
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 200_000)
                except ValueError:
                    n = 0
                raw = self.rfile.read(n)
                if path == "/login":
                    ip = self.client_address[0]
                    fails = srv._fails.get(ip, 0)
                    if fails >= 5:
                        time.sleep(2)        # freia quem tenta adivinhar a senha
                    pw = parse_qs(raw.decode("utf-8", "replace")).get("password", [""])[0]
                    if srv.password and hmac.compare_digest(pw.encode(), srv.password.encode()):
                        srv._fails.pop(ip, None)
                        tok = secrets.token_urlsafe(24)
                        srv._sessions[tok] = time.time() + 30 * 86400
                        return self._send(303, "", extra={
                            "Location": "/",
                            "Set-Cookie": f"sdm={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"})
                    srv._fails[ip] = fails + 1
                    time.sleep(0.8)
                    return self._send(200, localize(LOGIN_HTML.replace("%ERR%", '<div class="e">Senha incorreta</div>')))
                if not self._authed() or not self.headers.get("X-Scarlet-Remote"):
                    return self._send(401, "{}", "application/json")
                try:
                    data = json.loads(raw or b"{}")
                    if not isinstance(data, dict):
                        raise ValueError
                except ValueError:
                    return self._send(400, "{}", "application/json")
                if path == "/api/add":
                    urls = [u for u in data.get("urls", []) if isinstance(u, str)
                            and u.lower().startswith(("http://", "https://", "ftp://", "magnet:?"))][:200]
                    if urls:
                        srv.bridge.action.emit({"action": "add", "urls": urls})
                    return self._send(200, json.dumps({"ok": bool(urls)}), "application/json")
                if path == "/api/action":
                    act = data.get("action")
                    if act in ("pause", "start", "pause_all", "resume_all"):
                        srv.bridge.action.emit({"action": act, "id": str(data.get("id", ""))})
                        return self._send(200, '{"ok":true}', "application/json")
                return self._send(404, "{}", "application/json")

        try:
            self.httpd = LocalHTTPServer(("0.0.0.0", int(port)), Handler)
        except OSError as e:
            self.httpd = None
            self.error = str(e)
            return False
        self.httpd.daemon_threads = True
        self.port = int(port)
        self.error = ""
        threading.Thread(target=self.httpd.serve_forever, name="remote", daemon=True).start()
        return True

    def stop(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
        self.httpd = None
