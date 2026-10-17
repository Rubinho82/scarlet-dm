"""Download HTTP/HTTPS com várias conexões.

Estratégia (a mesma observada no downloadswww.dll do FDM, com melhorias):
- a 1ª conexão pede `Range: bytes=0-` e serve ao mesmo tempo de sondagem e de seção 0;
- cada conexão extra nasce cortando ao meio a seção com mais bytes faltando;
- as conexões pedem faixas abertas (`bytes=N-`), então uma seção pode encolher enquanto
  baixa, sem reconectar: ela só para ao chegar no início da vizinha;
- o arquivo .sdm é esparso e já tem o tamanho final, cada conexão grava na sua posição.
"""
import errno
import hashlib
import os
import re
import threading
import time
import urllib.parse

import requests
from requests.adapters import HTTPAdapter

from .task import (Task, Stopped, STARTING, DOWNLOADING, PROCESSING, COMPLETED, ERROR, QUEUED)
from ..i18n import _
from ..util import (filename_from_content_disposition, filename_from_url, guess_extension,
                    sanitize_filename, set_sparse, set_file_size, free_space, format_size)

CHUNK = 64 * 1024
MIN_PIECE = 512 * 1024          # cada metade de um corte precisa ter pelo menos isso
PART_EXT = ".sdm"
_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.I)
_FATAL_CODES = {400, 401, 402, 403, 404, 405, 406, 410, 451}


class HttpError(Exception):
    def __init__(self, code, reason, fatal):
        super().__init__(f"HTTP {code} {reason}".strip())
        self.code = code
        self.fatal = fatal


class NoRangeSupport(Exception):
    pass


class FileChanged(Exception):
    pass


class SwitchToHls(Exception):
    pass


class Segment:
    __slots__ = ("start", "end", "pos", "active", "fails")

    def __init__(self, start, end, pos=None):
        self.start = start
        self.end = end            # exclusivo; -1 = tamanho desconhecido
        self.pos = start if pos is None else pos
        self.active = False
        self.fails = 0

    def complete(self):
        return self.end >= 0 and self.pos >= self.end

    def remaining(self):
        return self.end - self.pos if self.end >= 0 else -1


class HttpTask(Task):
    kind = "http"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.segments = []
        self.resumable = None
        self.etag = ""
        self.last_modified = ""
        self.final_url = ""
        self.content_type = ""
        self.verified = None
        self.max_conns = 1
        self._fatal = None
        self._responses = set()
        self._workers = []
        self._split_at = 0.0

    # ---------- propriedades ----------
    @property
    def part_path(self):
        return self.path + PART_EXT

    @property
    def done(self):
        with self.lock:
            return sum(max(0, s.pos - s.start) for s in self.segments)

    @property
    def connections_active(self):
        with self.lock:
            return sum(1 for s in self.segments if s.active)

    @property
    def active_nolock(self):
        # leitura sem trava: usada pelo gerenciador ao somar conexões de várias tarefas (evita deadlock)
        return sum(1 for s in list(self.segments) if s.active)

    @property
    def host(self):
        import urllib.parse
        try:
            return (urllib.parse.urlsplit(self.final_url or self.url).hostname or "").lower()
        except ValueError:
            return ""

    def is_retryable(self, e):
        if isinstance(e, HttpError):
            return not e.fatal and e.code != 416
        if isinstance(e, OSError) and (e.errno == errno.ENOSPC or getattr(e, "winerror", 0) == 112):
            return False
        if isinstance(e, (requests.exceptions.SSLError, FileChanged)):
            return False
        if isinstance(e, requests.RequestException):
            return True
        return super().is_retryable(e)

    def describe_error(self, e):
        if isinstance(e, HttpError):
            if e.code in (401, 403):
                return f"{e} — " + _("acesso negado ou link expirado (use “Alterar link”)")
            if e.code in (404, 410):
                return f"{e} — " + _("o arquivo não existe mais no servidor")
            return str(e)
        if isinstance(e, requests.exceptions.SSLError):
            return _("Erro de certificado SSL (desative a verificação nas Preferências se confiar no site)")
        if isinstance(e, requests.exceptions.ConnectionError):
            return _("Não foi possível conectar ao servidor")
        if isinstance(e, requests.exceptions.Timeout):
            return _("O servidor parou de responder")
        if isinstance(e, OSError) and (e.errno == errno.ENOSPC or getattr(e, "winerror", 0) == 112):
            return e.strerror if getattr(e, "scarlet_msg", False) else _("Disco cheio")
        return super().describe_error(e)

    # ---------- rede ----------
    def _session(self):
        st = self.manager.settings
        s = requests.Session()
        mode = st.get("proxy_mode", "none")
        s.trust_env = mode == "system"
        if mode == "manual" and st.get("proxy_url"):
            s.proxies = {"http": st["proxy_url"], "https": st["proxy_url"]}
        s.verify = bool(st.get("verify_ssl", True))
        s.max_redirects = 20
        ad = HTTPAdapter(pool_connections=1, pool_maxsize=2, max_retries=0)
        s.mount("http://", ad)
        s.mount("https://", ad)
        return s

    def _headers(self, start, if_range):
        o = self.options
        st = self.manager.settings
        h = {
            "User-Agent": o.get("user_agent") or st.get("user_agent"),
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        if o.get("referer"):
            h["Referer"] = o["referer"]
        if o.get("cookies"):
            h["Cookie"] = o["cookies"]
        for k, v in (o.get("headers") or {}).items():
            if k.lower() not in ("range", "accept-encoding", "if-range", "content-length", "host"):
                h[k] = v
        h["Range"] = f"bytes={start}-"
        if if_range:
            v = self.etag if self.etag and not self.etag.startswith("W/") else self.last_modified
            if v:
                h["If-Range"] = v
        return h

    def _open(self, sess, start, if_range):
        if self.stopped():
            raise Stopped()
        st = self.manager.settings
        post = self.options.get("post_data")
        r = sess.request("POST" if post else "GET", self.url, headers=self._headers(start, if_range),
                         data=post or None, stream=True, allow_redirects=True,
                         timeout=(15, max(5, int(st.get("timeout", 30)))))
        with self.lock:
            self._responses.add(r)
        if self.stopped():
            self._close(r)
            raise Stopped()
        if r.status_code in (200, 206, 416):
            return r
        code, reason = r.status_code, r.reason
        ra = r.headers.get("Retry-After", "").strip()
        self._close(r)
        err = HttpError(code, reason, code in _FATAL_CODES)
        err.retry_after = int(ra) if ra.isdigit() else 0
        raise err

    def _close(self, r):
        if r is None:
            return
        with self.lock:
            self._responses.discard(r)
        try:
            r.close()
        except Exception:
            pass

    def on_stop(self):
        # Fecha os sockets para destravar leituras bloqueadas: a pausa é imediata.
        with self.lock:
            rs = list(self._responses)
        for r in rs:
            try:
                r.close()
            except Exception:
                pass

    def _iter(self, r):
        enc = r.headers.get("Content-Encoding", "").lower()
        if enc not in ("", "identity") and not self.resumable:
            return r.iter_content(CHUNK)
        return r.raw.stream(CHUNK, decode_content=False)

    def _retry_delay(self, attempts):
        return min(30, 2 ** min(attempts, 5))

    def _open_with_retry(self, sess, start, if_range):
        retries = int(self.manager.settings.get("retries", 10))
        attempts = 0
        while True:
            try:
                return self._open(sess, start, if_range)
            except HttpError as e:
                if e.fatal:
                    raise
                err = e
            except (requests.RequestException, OSError) as e:
                err = e
            if self.stopped():
                raise Stopped()
            attempts += 1
            if attempts > retries:
                raise err
            d = max(self._retry_delay(attempts), min(getattr(err, "retry_after", 0) or 0, 120))
            self.logmsg(f"Falha ao conectar ({self.describe_error(err)}); nova tentativa em {d}s")
            if self._halt.wait(d):
                raise Stopped()

    # ---------- sondagem ----------
    def _apply_probe(self, r, keep_name=False):
        self.final_url = r.url
        self.content_type = r.headers.get("Content-Type", "")
        enc = r.headers.get("Content-Encoding", "").lower()
        if r.status_code == 206:
            m = _CONTENT_RANGE.search(r.headers.get("Content-Range", ""))
            total = int(m.group(3)) if m and m.group(3) != "*" else -1
            self.resumable = True
        else:
            cl = r.headers.get("Content-Length", "")
            total = int(cl) if cl.isdigit() and enc in ("", "identity") else -1
            self.resumable = False
        ct = self.content_type.lower()
        if "mpegurl" in ct and (total < 0 or total < 5 * 1024 * 1024):
            raise SwitchToHls()
        path_ext = os.path.splitext(urllib.parse.urlsplit(r.url).path)[1].lower()
        if (ct.startswith("text/html") and self.manager.settings.get("skip_html", True)
                and path_ext not in (".htm", ".html", ".php", ".asp", ".aspx") and not self.options.get("allow_html")):
            raise HttpError(r.status_code, "— " + _("o link abriu uma página da web, não um arquivo "
                                           "(pode exigir login ou o link expirou)"), True)
        self.total = total
        self.etag = r.headers.get("ETag", "")
        self.last_modified = r.headers.get("Last-Modified", "")
        if not keep_name:
            name = self.filename if self.filename_fixed else (
                filename_from_content_disposition(r.headers.get("Content-Disposition"))
                or filename_from_url(r.url))
            if not os.path.splitext(name)[1]:
                name += guess_extension(self.content_type)
            self.filename = self.manager.reserve_filename(self, self.save_dir, sanitize_filename(name))
        size = f"{total} bytes" if total >= 0 else "tamanho desconhecido"
        self.logmsg(f"Resposta {r.status_code}: {size}, retomada {'sim' if self.resumable else 'não'}, "
                    f"tipo {self.content_type or '?'}")
        if r.url != self.url:
            self.logmsg(f"Redirecionado para {r.url}")
        self.dirty = True

    def _prepare_file(self, fresh):
        os.makedirs(self.save_dir, exist_ok=True)
        part = self.part_path
        if fresh or not os.path.exists(part):
            with open(part, "wb"):
                pass
            set_sparse(part)
        if self.total >= 0 and os.path.getsize(part) != self.total:
            set_file_size(part, self.total)

    # ---------- execução ----------
    def run(self):
        st = self.manager.settings
        self.max_conns = max(1, min(32, int(self.options.get("connections") or st.get("connections", 8))))
        self._fatal = None
        self._workers = []
        sess = self._session()
        self.status = STARTING
        fresh = not self.segments or not os.path.exists(self.part_path)

        if fresh:
            with self.lock:
                self.segments = []
            self.logmsg(f"Conectando a {self.url}")
            r = self._open_with_retry(sess, 0, if_range=False)
            if r.status_code == 416:      # arquivo vazio
                self._close(r)
                self.total, self.resumable = 0, False
                if not self.filename_fixed:
                    self.filename = self.manager.reserve_filename(
                        self, self.save_dir, sanitize_filename(filename_from_url(self.url)))
                self._prepare_file(fresh=True)
                return self._finalize()
            try:
                self._apply_probe(r)
            except SwitchToHls:
                self._close(r)
                self.logmsg("O link é uma playlist HLS (.m3u8); trocando para o modo de streaming")
                self.convert_to = "hls"
                self.status = PROCESSING
                return
            self._prepare_file(fresh=True)
            seg = Segment(0, self.total if self.total >= 0 else -1)
            with self.lock:
                self.segments = [seg]
        else:
            with self.lock:
                for s in self.segments:
                    s.active = False
                seg = next((s for s in self.segments if not s.complete()), None)
            if seg is None:
                return self._finalize()
            self.logmsg(f"Retomando a partir do byte {seg.pos}")
            r = self._open_with_retry(sess, seg.pos, if_range=True)
            if not self._resume_ok(r, seg):
                self.logmsg("O servidor não aceitou retomar (arquivo mudou ou sem suporte); recomeçando do zero")
                if r.status_code != 200:
                    self._close(r)
                    r = self._open_with_retry(sess, 0, if_range=False)
                self._apply_probe(r, keep_name=True)
                self._prepare_file(fresh=True)
                seg = Segment(0, self.total if self.total >= 0 else -1)
                with self.lock:
                    self.segments = [seg]
            else:
                self._prepare_file(fresh=False)

        if self.total > 0:
            need = self.total - self.done
            free = free_space(self.save_dir)
            if 0 <= free < need:
                self._close(r)
                err = OSError(errno.ENOSPC, _("Espaço insuficiente em {disco}: faltam {falta}, livre {livre}").format(
                    disco=os.path.splitdrive(self.save_dir)[0] or self.save_dir, falta=format_size(need),
                    livre=format_size(free)))
                err.scarlet_msg = True
                raise err
        if not self.resumable:
            self.max_conns = 1
        self.status = DOWNLOADING
        self._spawn(seg, r, sess)

        while not self._halt.wait(0.15):
            with self.lock:
                if self._fatal is not None:
                    break
                if self.segments and all(s.complete() for s in self.segments):
                    break
                if not any(s.active for s in self.segments):
                    if not self._has_work():
                        break
                    if all(s.fails >= 3 for s in self.segments if not s.complete()):
                        self._fatal = RuntimeError(_("O servidor deixou de aceitar downloads em partes"))
                        break
            self._fill()

        self._halt.set()
        self.on_stop()
        for t in list(self._workers):
            t.join(10)
        if self._stop.is_set():
            raise Stopped()
        if self._fatal is not None:
            raise self._fatal
        with self.lock:
            incomplete = [s for s in self.segments if not s.complete()]
        if incomplete:
            raise RuntimeError(_("Download interrompido antes do fim"))
        self._finalize()

    def _has_work(self):
        return any(not s.complete() for s in self.segments)

    def _resume_ok(self, r, seg):
        if r.status_code == 416:
            return self.total >= 0 and seg.pos >= self.total
        if r.status_code != 206:
            return seg.pos == 0 and not self.resumable
        m = _CONTENT_RANGE.search(r.headers.get("Content-Range", ""))
        if not m or int(m.group(1)) != seg.pos:
            return False
        if m.group(3) != "*" and self.total >= 0 and int(m.group(3)) != self.total:
            return False
        return True

    def _spawn(self, seg, resp=None, sess=None):
        seg.active = True
        t = threading.Thread(target=self._worker, args=(seg, resp, sess), daemon=True,
                             name=f"seg-{self.id}-{seg.start}")
        self._workers.append(t)
        t.start()

    def _fill(self):
        new = []
        budget = self.manager.conn_budget(self)     # fora da trava: lê outras tarefas
        with self.lock:
            if self._halt.is_set():
                return
            slots = min(self.max_conns - sum(1 for s in self.segments if s.active), budget)
            if slots <= 0:
                return
            for s in self.segments:
                if slots <= 0:
                    break
                if not s.active and not s.complete() and s.fails < 3:
                    s.active = True
                    new.append(s)
                    slots -= 1
            now = time.monotonic()
            # Uma conexão nova por vez, como o FDM ("already creating"), para não martelar o servidor.
            if slots > 0 and not new and self.resumable and self.total >= 0 and now - self._split_at > 0.3:
                s = self._split()
                if s is not None:
                    s.active = True
                    new.append(s)
                    self._split_at = now
        for s in new:
            self._spawn(s)

    def _split(self):
        best, best_rem = None, 0
        for s in self.segments:
            rem = s.remaining()
            if rem > best_rem:
                best, best_rem = s, rem
        if best is None or best_rem < 2 * MIN_PIECE:
            return None
        mid = best.pos + best_rem // 2
        mid -= mid % 4096
        if mid - best.pos < MIN_PIECE:
            return None
        new = Segment(mid, best.end)
        best.end = mid
        self.segments.insert(self.segments.index(best) + 1, new)
        self.dirty = True
        return new

    def _set_fatal(self, e):
        with self.lock:
            if self._fatal is None:
                self._fatal = e
        self._halt.set()
        self.on_stop()

    def _worker(self, seg, resp, sess):
        st = self.manager.settings
        retries = int(st.get("retries", 10))
        limiter = self.manager.limiter
        sess = sess or self._session()
        attempts = 0
        f = None
        try:
            f = open(self.part_path, "r+b")
            while not self._halt.is_set():
                with self.lock:
                    if seg.complete():
                        break
                    start = seg.pos
                try:
                    if resp is None:
                        resp = self._open(sess, start, if_range=True)
                        if resp.status_code == 416:
                            if self.total >= 0 and start >= self.total:
                                with self.lock:
                                    seg.end = min(seg.end, start) if seg.end >= 0 else start
                                break
                            raise HttpError(416, _("faixa inválida"), False)
                        if start > 0:
                            if resp.status_code != 206:
                                raise NoRangeSupport()
                            m = _CONTENT_RANGE.search(resp.headers.get("Content-Range", ""))
                            if not m or int(m.group(1)) != start:
                                raise NoRangeSupport()
                            if m.group(3) != "*" and self.total >= 0 and int(m.group(3)) != self.total:
                                raise FileChanged()
                    f.seek(start)
                    for chunk in self._iter(resp):
                        if self._halt.is_set():
                            break
                        limiter.consume(len(chunk), self._halt)
                        with self.lock:
                            if seg.end >= 0:
                                allowed = seg.end - seg.pos
                                if allowed <= 0:
                                    chunk = b""
                                elif len(chunk) > allowed:
                                    chunk = chunk[:allowed]
                            seg.pos += len(chunk)
                        if not chunk:
                            break
                        try:
                            f.write(chunk)
                        except OSError as e:
                            self._set_fatal(e)
                            return
                        attempts = 0
                    if self._halt.is_set():
                        break
                    with self.lock:
                        if seg.end < 0:          # tamanho desconhecido: fim do corpo = fim do arquivo
                            seg.end = seg.pos
                            self.total = seg.pos
                            self.dirty = True
                            break
                        if seg.complete():
                            break
                    raise requests.exceptions.ChunkedEncodingError("conexão encerrada antes do fim")
                except Stopped:
                    break
                except NoRangeSupport:
                    with self.lock:
                        seg.fails += 1
                        others = sum(1 for s in self.segments if s.active and s is not seg)
                        self.max_conns = max(1, others)
                        if seg.fails >= 3 and not others:
                            self._set_fatal(RuntimeError(_("O servidor deixou de aceitar downloads em partes")))
                    self.logmsg(f"Seção em {start}: servidor ignorou o Range; reduzindo conexões")
                    break
                except FileChanged:
                    self._set_fatal(RuntimeError(_("O arquivo no servidor mudou de tamanho; use “Reiniciar”")))
                    break
                except HttpError as e:
                    if e.fatal:
                        self._set_fatal(e)
                        break
                    if e.code in (429, 503):
                        # O servidor quer menos conexões: esta sai e devolve a seção para a fila,
                        # o teto cai para as que sobraram e novas conexões esperam 15 s.
                        with self.lock:
                            others = sum(1 for s in self.segments if s.active and s is not seg)
                            if others:
                                self.max_conns = max(1, min(self.max_conns, others))
                            self._split_at = time.monotonic() + 15
                        if others:
                            self.logmsg(f"Servidor pediu menos conexões (HTTP {e.code}); "
                                        f"continuando com {self.max_conns}")
                            break
                    attempts += 1
                    if not self._backoff(attempts, retries, e, start, getattr(e, "retry_after", 0)):
                        break
                except Exception as e:  # noqa: BLE001 - urllib3/socket fechado/timeout: tudo vira nova tentativa
                    if self._halt.is_set():
                        break
                    attempts += 1
                    if not self.resumable:
                        with self.lock:
                            seg.pos = seg.start
                        if seg.end < 0:
                            f.truncate(0)
                    if not self._backoff(attempts, retries, e, start):
                        break
                finally:
                    self._close(resp)
                    resp = None
        except OSError as e:
            self._set_fatal(e)
        finally:
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
            with self.lock:
                seg.active = False
            self.dirty = True

    def _backoff(self, attempts, retries, err, start, min_delay=0):
        if attempts > retries:
            self._set_fatal(err)
            return False
        d = max(self._retry_delay(attempts), min(int(min_delay or 0), 120))
        self.logmsg(f"Seção em {start}: {self.describe_error(err)}; nova tentativa em {d}s "
                    f"({attempts}/{retries})")
        return not self._halt.wait(d)

    # ---------- conclusão ----------
    def _finalize(self):
        self.status = PROCESSING
        part = self.part_path
        if self.total < 0:
            self.total = self.done
        if os.path.exists(part) and os.path.getsize(part) != self.total:
            set_file_size(part, self.total)
        final = self.manager.final_path(self)
        for i in range(10):
            try:
                os.replace(part, final)
                break
            except PermissionError:
                # antivírus/indexador costuma segurar o arquivo por alguns instantes
                if i == 9:
                    raise
                time.sleep(0.5)
        self.filename = os.path.basename(final)
        self.logmsg(f"Salvo em {final}")
        cs = self.options.get("checksum") or {}
        if cs.get("value"):
            self.verified = self.verify_checksum(cs.get("algo", "sha256"), cs["value"])
            if not self.verified:
                self.status = ERROR
                self.error = _("Checksum {algo} não confere").format(algo=cs.get("algo", "sha256").upper())
                self.finished = time.time()
                return
        self.status = COMPLETED
        self.finished = time.time()
        self.dirty = True

    def verify_checksum(self, algo, expected):
        h = hashlib.new(algo.lower())
        with open(self.path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        ok = h.hexdigest().lower() == expected.strip().lower()
        self.logmsg(f"{algo.upper()}: {h.hexdigest()} — {'confere' if ok else 'NÃO confere'}")
        return ok

    # ---------- manutenção ----------
    def reset(self):
        super().reset()
        with self.lock:
            self.segments = []
        self.resumable = None
        self.etag = self.last_modified = ""
        self.verified = None

    def delete_files(self, include_completed=True):
        targets = [self.part_path]
        if include_completed and self.status == COMPLETED:
            targets.append(self.path)
        for p in targets:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    def to_dict(self):
        d = super().to_dict()
        with self.lock:
            d["segments"] = [[s.start, s.end, s.pos] for s in self.segments]
        d.update(resumable=self.resumable, etag=self.etag, last_modified=self.last_modified,
                 final_url=self.final_url, content_type=self.content_type, verified=self.verified)
        return d

    def load_dict(self, d):
        super().load_dict(d)
        self.segments = [Segment(a, b, c) for a, b, c in d.get("segments", [])]
        self.resumable = d.get("resumable")
        self.etag = d.get("etag", "")
        self.last_modified = d.get("last_modified", "")
        self.final_url = d.get("final_url", "")
        self.content_type = d.get("content_type", "")
        self.verified = d.get("verified")
