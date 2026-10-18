"""Download de streams HLS (.m3u8) sob demanda.

Baixa os pedaços em paralelo, decifra AES-128 quando a playlist manda,
e junta tudo num .mp4 com o ffmpeg (ou .ts se o ffmpeg não existir).
Transmissões ao vivo e conteúdo com DRM (SAMPLE-AES etc.) não são suportados.
"""
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.parse

import requests
from requests.adapters import HTTPAdapter

from .task import Task, Stopped, STARTING, DOWNLOADING, PROCESSING, COMPLETED
from .http_task import HttpError, _FATAL_CODES
from ..i18n import _
from ..util import filename_from_url, sanitize_filename, find_ffmpeg

_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def parse_attrs(s):
    return {k: v.strip('"') for k, v in _ATTR.findall(s)}


def _br(value, next_off=0):
    if not value:
        return None
    n, _, o = value.partition("@")
    return int(n), int(o) if o else next_off


def parse_master(text, base):
    variants, audio = [], {}
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            a = parse_attrs(line.split(":", 1)[1])
            j = i + 1
            while j < len(lines) and (not lines[j] or lines[j].startswith("#")):
                j += 1
            if j < len(lines):
                variants.append({
                    "bw": int(a.get("BANDWIDTH") or a.get("AVERAGE-BANDWIDTH") or 0),
                    "res": a.get("RESOLUTION", ""),
                    "audio": a.get("AUDIO"),
                    "url": urllib.parse.urljoin(base, lines[j]),
                })
        elif line.startswith("#EXT-X-MEDIA:"):
            a = parse_attrs(line.split(":", 1)[1])
            if a.get("TYPE") == "AUDIO" and a.get("URI"):
                audio.setdefault(a.get("GROUP-ID"), []).append({
                    "url": urllib.parse.urljoin(base, a["URI"]),
                    "default": a.get("DEFAULT") == "YES",
                    "name": a.get("NAME", ""),
                })
    return variants, audio


def parse_media(text, base, track):
    items, key, seq, endlist = [], None, 0, False
    pending_br, next_off, last_map = None, 0, None
    for line in (ln.strip() for ln in text.splitlines()):
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            seq = int(line.split(":", 1)[1] or 0)
        elif line.startswith("#EXT-X-KEY:"):
            a = parse_attrs(line.split(":", 1)[1])
            method = a.get("METHOD", "NONE").upper()
            if method == "NONE":
                key = None
            elif method == "AES-128":
                key = {"uri": urllib.parse.urljoin(base, a["URI"]), "iv": a.get("IV")}
            else:
                raise RuntimeError(_("Conteúdo protegido ({metodo}/DRM) não é suportado").format(metodo=method))
        elif line.startswith("#EXT-X-MAP:"):
            a = parse_attrs(line.split(":", 1)[1])
            m = {"url": urllib.parse.urljoin(base, a["URI"]), "track": track, "init": True,
                 "key": None, "br": _br(a.get("BYTERANGE"))}
            sig = (m["url"], m["br"])
            if sig != last_map:
                items.append(m)
                last_map = sig
        elif line.startswith("#EXT-X-BYTERANGE:"):
            pending_br = _br(line.split(":", 1)[1], next_off)
            next_off = pending_br[0] + pending_br[1]
        elif line.startswith("#EXT-X-ENDLIST"):
            endlist = True
        elif line and not line.startswith("#"):
            items.append({"url": urllib.parse.urljoin(base, line), "track": track, "init": False,
                          "key": dict(key, seq=seq) if key else None, "br": pending_br})
            pending_br = None
            seq += 1
    return items, endlist


class HlsTask(Task):
    kind = "hls"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.items = []
        self.done_set = set()
        self.bytes_done = 0
        self.variant_info = ""
        self.has_audio = False
        self._keys = {}
        self._responses = set()
        self._active = 0
        self._fatal = None
        if not self.filename:
            self.filename = self._default_name()

    def _default_name(self):
        title = (self.options.get("title") or "").strip()
        if title:
            return sanitize_filename(title) + ".mp4"
        base = os.path.splitext(filename_from_url(self.url))[0]
        if base.lower() in ("index", "playlist", "master", "main", "manifest", "video", "chunklist", ""):
            host = urllib.parse.urlsplit(self.url).hostname or "stream"
            base = f"{host}-{time.strftime('%Y%m%d-%H%M%S')}"
        return sanitize_filename(base) + ".mp4"

    @property
    def done(self):
        return self.bytes_done

    @property
    def connections_active(self):
        return self._active

    @property
    def tmp_dir(self):
        return os.path.join(self.save_dir, "." + self.name + ".sdm-hls")

    def est_total(self):
        if self.status == COMPLETED:
            return self.total
        n = len(self.done_set)
        if n and self.items:
            return int(self.bytes_done / n * len(self.items))
        return -1

    def progress(self):
        if self.status == COMPLETED:
            return 1.0
        if self.items:
            return len(self.done_set) / len(self.items)
        return None

    def eta(self):
        est = self.est_total()
        if self.speed <= 0 or est <= 0:
            return None
        return max(0, est - self.bytes_done) / self.speed

    # ---------- rede ----------
    def _session(self):
        st = self.manager.settings
        s = requests.Session()
        mode = st.get("proxy_mode", "none")
        s.trust_env = mode == "system"
        if mode == "manual" and st.get("proxy_url"):
            s.proxies = {"http": st["proxy_url"], "https": st["proxy_url"]}
        s.verify = bool(st.get("verify_ssl", True))
        n = max(2, int(self.options.get("connections") or st.get("connections", 8)))
        ad = HTTPAdapter(pool_connections=4, pool_maxsize=n + 2, max_retries=0)
        s.mount("http://", ad)
        s.mount("https://", ad)
        return s

    def _headers(self, br=None):
        o, st = self.options, self.manager.settings
        h = {"User-Agent": o.get("user_agent") or st.get("user_agent"), "Accept": "*/*"}
        if o.get("referer"):
            h["Referer"] = o["referer"]
            p = urllib.parse.urlsplit(o["referer"])
            h.setdefault("Origin", f"{p.scheme}://{p.netloc}")
        if o.get("cookies"):
            h["Cookie"] = o["cookies"]
        for k, v in (o.get("headers") or {}).items():
            if k.lower() not in ("range", "host", "content-length"):
                h[k] = v
        if br:
            h["Range"] = f"bytes={br[1]}-{br[1] + br[0] - 1}"
        return h

    def _get(self, sess, url, br=None, limit=True):
        if self.stopped():
            raise Stopped()
        st = self.manager.settings
        r = sess.get(url, headers=self._headers(br), stream=True, allow_redirects=True,
                     timeout=(15, max(5, int(st.get("timeout", 30)))))
        with self.lock:
            self._responses.add(r)
        buf = bytearray()
        try:
            if r.status_code not in (200, 206):
                raise HttpError(r.status_code, r.reason, r.status_code in _FATAL_CODES)
            for chunk in r.iter_content(64 * 1024):
                if self.stopped():
                    raise Stopped()
                if limit:
                    self.manager.limiter.consume(len(chunk), self._halt)
                    self.manager.task_limiter(self).consume(len(chunk), self._halt)
                    with self.lock:
                        self.bytes_done += len(chunk)
                buf += chunk
            return bytes(buf)
        except Exception:
            if limit:
                with self.lock:
                    self.bytes_done -= len(buf)
            raise
        finally:
            with self.lock:
                self._responses.discard(r)
            r.close()

    def on_stop(self):
        with self.lock:
            rs = list(self._responses)
        for r in rs:
            try:
                r.close()
            except Exception:
                pass

    # ---------- execução ----------
    def run(self):
        st = self.manager.settings
        sess = self._session()
        self.status = STARTING
        self._fatal = None
        if not self.items:
            self._load_playlists(sess)
        os.makedirs(self.tmp_dir, exist_ok=True)
        self._scan_existing()
        self.status = DOWNLOADING
        pending = queue.Queue()
        for i in range(len(self.items)):
            if i not in self.done_set:
                pending.put(i)
        n = max(1, min(16, int(self.options.get("connections") or st.get("connections", 8))))
        workers = [threading.Thread(target=self._worker, args=(sess, pending), daemon=True)
                   for _ in range(min(n, max(1, pending.qsize())))]
        for w in workers:
            w.start()
        for w in workers:
            while w.is_alive():
                w.join(0.3)
        if self._stop.is_set():
            raise Stopped()
        if self._fatal is not None:
            raise self._fatal
        if len(self.done_set) != len(self.items):
            raise RuntimeError(_("Nem todos os pedaços foram baixados"))
        self._merge()

    def _load_playlists(self, sess):
        self.logmsg(f"Lendo playlist {self.url}")
        text = self._get(sess, self.url, limit=False).decode("utf-8", "replace")
        if "#EXTM3U" not in text:
            raise RuntimeError(_("O link não é uma playlist HLS válida"))
        media_url, audio_url = self.url, None
        if "#EXT-X-STREAM-INF" in text:
            variants, audio = parse_master(text, self.url)
            if not variants:
                raise RuntimeError(_("Playlist mestre sem variantes"))
            pick = self.manager.settings.get("hls_quality", "best")
            variants.sort(key=lambda v: v["bw"])
            v = variants[0] if pick == "worst" else variants[-1]
            media_url = v["url"]
            self.variant_info = f"{v['res'] or '?'} · {v['bw'] / 1e6:.1f} Mbps".replace(".", ",")
            self.logmsg(f"Qualidade escolhida: {self.variant_info} ({len(variants)} opções)")
            group = audio.get(v.get("audio")) if v.get("audio") else None
            if group:
                a = next((x for x in group if x["default"]), group[0])
                audio_url = a["url"]
                self.logmsg(f"Faixa de áudio separada: {a['name'] or 'padrão'}")
            text = self._get(sess, media_url, limit=False).decode("utf-8", "replace")
        items, endlist = parse_media(text, media_url, "v")
        if not endlist:
            raise RuntimeError(_("Transmissão ao vivo não é suportada (playlist sem #EXT-X-ENDLIST)"))
        if audio_url:
            atext = self._get(sess, audio_url, limit=False).decode("utf-8", "replace")
            aitems, _amedia = parse_media(atext, audio_url, "a")
            items += aitems
            self.has_audio = True
        if not items:
            raise RuntimeError(_("Playlist vazia"))
        self.items = items
        self.logmsg(f"{len(items)} pedaços para baixar")
        self.dirty = True

    def _seg_path(self, i):
        it = self.items[i]
        return os.path.join(self.tmp_dir, f"{it['track']}{i:06d}.seg")

    def _scan_existing(self):
        self.done_set = set()
        total = 0
        for i in range(len(self.items)):
            p = self._seg_path(i)
            if os.path.exists(p):
                self.done_set.add(i)
                total += os.path.getsize(p)
        self.bytes_done = total

    def _key(self, sess, uri):
        with self.lock:
            k = self._keys.get(uri)
        if k is None:
            k = self._get(sess, uri, limit=False)
            if len(k) != 16:
                raise RuntimeError(_("Chave AES-128 inválida"))
            with self.lock:
                self._keys[uri] = k
        return k

    def _decrypt(self, sess, data, key):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        k = self._key(sess, key["uri"])
        if key.get("iv"):
            iv = bytes.fromhex(key["iv"][2:] if key["iv"].lower().startswith("0x") else key["iv"]).rjust(16, b"\0")
        else:
            iv = int(key["seq"]).to_bytes(16, "big")
        dec = Cipher(algorithms.AES(k), modes.CBC(iv)).decryptor()
        out = dec.update(data) + dec.finalize()
        pad = out[-1] if out else 0
        if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
            out = out[:-pad]
        return out

    def _worker(self, sess, pending):
        retries = int(self.manager.settings.get("retries", 10))
        with self.lock:
            self._active += 1
        try:
            while not self._halt.is_set():
                try:
                    i = pending.get_nowait()
                except queue.Empty:
                    return
                it = self.items[i]
                attempts = 0
                while not self._halt.is_set():
                    try:
                        data = self._get(sess, it["url"], it.get("br"))
                        if it.get("key"):
                            data = self._decrypt(sess, data, it["key"])
                        p = self._seg_path(i)
                        with open(p + ".tmp", "wb") as f:
                            f.write(data)
                        os.replace(p + ".tmp", p)
                        with self.lock:
                            self.done_set.add(i)
                        break
                    except Stopped:
                        return
                    except HttpError as e:
                        if e.fatal:
                            self._fail(e)
                            return
                        err = e
                    except OSError as e:
                        if self._halt.is_set():
                            return
                        if getattr(e, "winerror", 0) == 112 or e.errno == 28:
                            self._fail(e)
                            return
                        err = e
                    except Exception as e:  # noqa: BLE001 - erro de rede vira nova tentativa
                        if self._halt.is_set():
                            return
                        err = e
                    attempts += 1
                    if attempts > retries:
                        self._fail(err)
                        return
                    d = min(30, 2 ** min(attempts, 5))
                    self.logmsg(f"Pedaço {i}: {err}; nova tentativa em {d}s")
                    if self._halt.wait(d):
                        return
        finally:
            with self.lock:
                self._active -= 1

    def _fail(self, e):
        with self.lock:
            if self._fatal is None:
                self._fatal = e
        self._halt.set()
        self.on_stop()

    def _concat(self, track, out):
        idx = [i for i, it in enumerate(self.items) if it["track"] == track]
        with open(out, "wb") as o:
            for i in idx:
                with open(self._seg_path(i), "rb") as f:
                    shutil.copyfileobj(f, o, 1024 * 1024)
        return any(self.items[i]["init"] for i in idx)

    def _merge(self):
        self.status = PROCESSING
        self.logmsg("Juntando os pedaços…")
        tmp_dir = self.tmp_dir          # o nome final pode mudar abaixo; a pasta temporária não
        vtmp = os.path.join(tmp_dir, "video.bin")
        fmp4 = self._concat("v", vtmp)
        atmp = None
        if self.has_audio:
            atmp = os.path.join(tmp_dir, "audio.bin")
            self._concat("a", atmp)
        ffmpeg = find_ffmpeg(self.manager.settings.get("ffmpeg_path", ""))
        base, _ = os.path.splitext(self.name)
        if ffmpeg:
            self.filename = base + ".mp4"
            final = self.manager.final_path(self)
            out_tmp = os.path.join(tmp_dir, "out.mp4")
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", vtmp]
            if atmp:
                cmd += ["-i", atmp, "-map", "0:v?", "-map", "0:a?", "-map", "1:a?"]
            cmd += ["-c", "copy", "-movflags", "+faststart", out_tmp]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            p = subprocess.run(cmd, capture_output=True, creationflags=flags)
            if p.returncode == 0 and os.path.exists(out_tmp):
                os.replace(out_tmp, final)
            else:
                self.logmsg("ffmpeg falhou: " + p.stderr.decode("utf-8", "replace")[-400:])
                ffmpeg = ""
        if not ffmpeg:
            self.filename = base + (".mp4" if fmp4 else ".ts")
            final = self.manager.final_path(self)
            os.replace(vtmp, final)
            if atmp:
                apath = os.path.splitext(final)[0] + (".audio.mp4" if fmp4 else ".audio.ts")
                os.replace(atmp, apath)
                self.logmsg(f"Sem ffmpeg: áudio salvo separado em {apath}")
        self.filename = os.path.basename(final)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        self.total = os.path.getsize(final)
        self.bytes_done = self.total
        self.logmsg(f"Salvo em {final}")
        self.status = COMPLETED
        self.finished = time.time()
        self.dirty = True

    def reset(self):
        super().reset()
        if not self.filename_fixed:
            self.filename = self._default_name()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.items = []
        self.done_set = set()
        self.bytes_done = 0

    def delete_files(self, include_completed=True):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if include_completed and self.status == COMPLETED and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

    def to_dict(self):
        d = super().to_dict()
        d.update(items=self.items, bytes_done=self.bytes_done, variant_info=self.variant_info,
                 has_audio=self.has_audio)
        return d

    def load_dict(self, d):
        super().load_dict(d)
        self.items = d.get("items", [])
        for it in self.items:
            if it.get("br"):
                it["br"] = tuple(it["br"])
        self.bytes_done = d.get("bytes_done", 0)
        self.variant_info = d.get("variant_info", "")
        self.has_audio = d.get("has_audio", False)
