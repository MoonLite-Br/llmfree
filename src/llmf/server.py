"""``llmf serve`` - an OpenAI-compatible HTTP server backed by llmf (stdlib only).

Point any OpenAI client at ``http://127.0.0.1:8000/v1`` and it uses the free endpoints, with fallback.

Local by default (127.0.0.1, no auth, no limits). ``public=True`` (``--public``, ``--cloudflare``) switches on
the hardening profile: mandatory API key, per-key / per-IP rate limits, ban after repeated auth failures,
IP allow/deny lists, body / token caps, strict CORS, security headers, socket timeouts, access log, and an
anti-bot proof of work for the web UI. It can also serve a web page or a child Node app (``web=`` / ``app_port=``).
"""

from __future__ import annotations

import hmac
import json
import math
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from . import _security as sec
from . import _web
from .client import Client
from .errors import AllProvidersFailed, LLMFError, ModelNotFound

MAX_BODY = 20 * 1024 * 1024  # base64 images can be large
APP_MAX_BODY = 25 * 1024 * 1024
ALIASES = ("auto", "fast", "best", "code", "vision", "reasoning")

_DEFAULTS: Dict[str, Any] = dict(
    api_key=None, cors=False, cors_origins=(), strict_models=False, fallback=True,
    max_concurrent=None, rate=None, ip_rate=None, session_rate=12, allow_ip=(), deny_ip=(),
    trust_proxy=False, max_body=None, max_tokens_cap=None, session_max_tokens=1024, log_file=None,
    ban_after=None, antibot=None, pow_bits=16, turnstile_secret=None, turnstile_sitekey=None,
    ui=False, web=None, app_port=None, csp=None, tls_cert=None, tls_key=None, public=False,
    socket_timeout=None, max_connections=None, secret=None, fetch=None, session_ttl=1800.0,
)
_LOCAL = dict(max_concurrent=48, rate=0, ip_rate=0, max_body=MAX_BODY, max_tokens_cap=0, ban_after=0,
              socket_timeout=60.0)
_PUBLIC = dict(max_concurrent=32, rate=120, ip_rate=240, max_body=1024 * 1024, max_tokens_cap=4096,
               ban_after=10, socket_timeout=30.0)
_ASSETS: Dict[str, bytes] = {}


def _asset(name: str) -> bytes:
    if name not in _ASSETS:
        import pkgutil

        data = pkgutil.get_data("llmf", "web/" + name)
        if data is None:  # pragma: no cover - packaging error
            raise FileNotFoundError(name)
        _ASSETS[name] = data
    return _ASSETS[name]


def _err(message: str, etype: str, code: Optional[str] = None) -> Dict[str, Any]:
    return {"error": {"message": message, "type": etype, "code": code}}


class _Config:
    def __init__(self, client: Client, opts: Dict[str, Any]) -> None:
        o = dict(_DEFAULTS)
        unknown = set(opts) - set(o)
        if unknown:
            raise TypeError("unknown server option(s): %s" % ", ".join(sorted(unknown)))
        o.update(opts)
        for k, v in (_PUBLIC if o["public"] else _LOCAL).items():
            if o[k] is None:
                o[k] = v
        self.client = client
        keys = o["api_key"]
        self.api_keys: List[str] = [keys] if isinstance(keys, str) else [k for k in (keys or ()) if k]
        self.generated_key: Optional[str] = None
        if o["public"] and not self.api_keys:
            self.generated_key = sec.new_api_key()
            self.api_keys.append(self.generated_key)
        self.kid = {k: sec.key_id(k) for k in self.api_keys}
        self.require_auth = bool(self.api_keys) or o["public"]
        self.public = o["public"]
        self.cors = bool(o["cors"])
        self.cors_origins = [x.rstrip("/") for x in o["cors_origins"]]
        self.strict_models, self.fallback = o["strict_models"], o["fallback"]
        self.slots = threading.BoundedSemaphore(o["max_concurrent"]) if o["max_concurrent"] > 0 else None
        self.allow = sec.parse_networks(o["allow_ip"])
        self.deny = sec.parse_networks(o["deny_ip"])
        self.trust_proxy = bool(o["trust_proxy"])
        self.max_body, self.max_tokens_cap = int(o["max_body"]), int(o["max_tokens_cap"])
        self.session_max_tokens = int(o["session_max_tokens"])
        self.socket_timeout = float(o["socket_timeout"])
        self.ip_limiter = sec.RateLimiter(o["ip_rate"], burst=max(10, o["ip_rate"] / 4))
        self.key_limiter = sec.RateLimiter(o["rate"], burst=max(5, o["rate"] / 4))
        self.session_limiter = sec.RateLimiter(o["session_rate"], burst=max(3, o["session_rate"] / 3))
        self.challenge_limiter = sec.RateLimiter(30 if o["public"] else 0, burst=10)
        self.bans = sec.BanList(after=int(o["ban_after"]))
        self.ui, self.csp = bool(o["ui"]), o["csp"]
        self.static = _web.StaticSite(o["web"]) if o["web"] else None
        self.app_port = o["app_port"]
        self.tls = bool(o["tls_cert"])
        self.sessions = bool(self.ui or self.static or self.app_port or o["antibot"])
        mode = o["antibot"] or ("pow" if o["public"] else "off")
        self.antibot: Optional[sec.Antibot] = None
        if self.sessions:
            self.antibot = sec.Antibot(
                mode, bits=o["pow_bits"], session_ttl=o["session_ttl"], secret=o["secret"],
                turnstile_secret=o["turnstile_secret"], turnstile_sitekey=o["turnstile_sitekey"],
                fetch=o["fetch"])
        self._log_lock = threading.Lock()
        self._log_fh = None
        if o["log_file"]:
            self._log_fh = sys.stderr if o["log_file"] == "-" else open(o["log_file"], "a", buffering=1, encoding="utf-8")

    def log(self, entry: Dict[str, Any]) -> None:
        if self._log_fh is None:
            return
        entry = dict(entry, t=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        with self._log_lock:
            try:
                self._log_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        if self._log_fh not in (None, sys.stderr):
            try:
                self._log_fh.close()
            except OSError:
                pass


class _Server(ThreadingHTTPServer):
    request_queue_size = 128     # the default (5) drops connections under a burst
    daemon_threads = True
    ssl_context: Optional[ssl.SSLContext] = None
    cfg: _Config
    conn_slots: Optional[threading.BoundedSemaphore] = None

    def process_request(self, request, client_address):
        # hard cap on simultaneous connections (threads): beyond it, drop instead of exhausting memory
        if self.conn_slots is not None and not self.conn_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            if self.conn_slots is not None:
                self.conn_slots.release()

    def handle_error(self, request, client_address):   # TLS probes / resets are noise, not tracebacks
        if isinstance(sys.exc_info()[1], (OSError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)

    def get_request(self):
        sock, addr = self.socket.accept()
        if self.ssl_context is not None:
            # Handshake happens later, in the handler thread, under the socket timeout (no slow-loris on accept()).
            sock = self.ssl_context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr


def _norm_ip(s: str) -> str:
    a = sec._addr(s.strip())
    return str(a) if a is not None else ""


def make_handler(cfg: _Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "llmf"
        sys_version = ""
        protocol_version = "HTTP/1.0"  # one request per connection; streams end on close
        timeout = cfg.socket_timeout

        def version_string(self) -> str:
            return "llmf"

        def log_message(self, fmt, *args):  # quiet by default
            pass

        # ------------------------------------------------------------ plumbing
        def send_response(self, code, message=None):
            self._status = code
            super().send_response(code, message)

        def send_header(self, keyword, value):
            self._sent.add(keyword.lower())
            super().send_header(keyword, value)

        def end_headers(self):
            def add(k: str, v: str) -> None:
                if k.lower() not in self._sent:
                    self.send_header(k, v)

            origin = (self.headers.get("Origin") or "").rstrip("/")
            if cfg.cors:
                add("Access-Control-Allow-Origin", "*")
            elif origin and origin in cfg.cors_origins:
                add("Access-Control-Allow-Origin", origin)
                add("Vary", "Origin")
            if "access-control-allow-origin" in self._sent:
                add("Access-Control-Allow-Headers", "authorization, content-type")
                add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            if not self._proxied:
                add("X-Content-Type-Options", "nosniff")
                add("Referrer-Policy", "no-referrer")
                add("X-Frame-Options", "SAMEORIGIN")
                add("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                if cfg.tls:
                    add("Strict-Transport-Security", "max-age=31536000")
            if cfg.csp:
                add("Content-Security-Policy", cfg.csp)
            super().end_headers()

        def _headers(self, code: int, ctype: str, length: Optional[int] = None, **extra: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            if ctype.startswith(("application/json", "text/event-stream")):
                self.send_header("Cache-Control", "no-store")
            for k, v in extra.items():
                self.send_header(k.replace("_", "-"), v)
            self.end_headers()

        def _json(self, code: int, obj: Any, **extra: str) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self._headers(code, "application/json", len(data), **extra)
            if self.command != "HEAD":
                self.wfile.write(data)

        def _limited(self, wait: float, message: str, code: str = "rate_limited") -> None:
            self._json(429, _err(message, "rate_limit_error", code), Retry_After=str(max(1, int(math.ceil(wait)))))

        def _bytes(self, data: bytes, ctype: str, csp: Optional[str] = None) -> None:
            self._headers(200, ctype, len(data), Cache_Control="no-cache", **({"Content_Security_Policy": csp} if csp else {}))
            if self.command != "HEAD":
                self.wfile.write(data)

        # ------------------------------------------------------------ identity
        def _ip(self) -> str:
            peer = _norm_ip(self.client_address[0]) or self.client_address[0]
            if cfg.trust_proxy and sec.is_loopback(peer):
                cf = _norm_ip(self.headers.get("CF-Connecting-IP", ""))
                if cf:
                    return cf
                xff = self.headers.get("X-Forwarded-For", "")
                if xff:
                    last = _norm_ip(xff.split(",")[-1])   # the hop our trusted proxy saw
                    if last:
                        return last
            return peer

        def _scheme(self) -> str:
            if cfg.trust_proxy and sec.is_loopback(_norm_ip(self.client_address[0])):
                fp = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
                if fp in ("http", "https"):
                    return fp
            return "https" if cfg.tls else "http"

        def _bearer(self) -> str:
            got = self.headers.get("Authorization", "")
            return got[7:].strip() if got[:7].lower() == "bearer " else ""

        def _is_credential(self, header_value: str) -> bool:
            tok = header_value[7:].strip() if header_value[:7].lower() == "bearer " else ""
            return bool(tok) and (tok.startswith(sec.SESSION_PREFIX)
                                  or any(hmac.compare_digest(tok.encode(), k.encode()) for k in cfg.api_keys))

        def _principal(self, ip: str):
            tok = self._bearer()
            if tok:
                tb = tok.encode()
                found = None
                for k in cfg.api_keys:                  # no early exit: constant work per request
                    if hmac.compare_digest(tb, k.encode()):
                        found = k
                if found is not None:
                    return ("key", cfg.kid[found])
                if cfg.antibot is not None and cfg.antibot.valid_token(tok, ip):
                    return ("session", ip)
            if not cfg.require_auth:
                return ("anon", ip)
            return None

        def _deny_auth(self, ip: str) -> None:
            banned = cfg.bans.strike(ip)
            self._json(401, _err("invalid or missing credentials", "invalid_request_error", "invalid_api_key"),
                       WWW_Authenticate='Bearer realm="llmf"')
            if banned:
                cfg.log({"event": "ban", "ip": ip})

        # ------------------------------------------------------------- entry
        def _entry(self, method: str) -> None:
            self._t0 = time.monotonic()
            self._status, self._who, self._mname = 0, "-", None
            self._sent: set = set()
            self._proxied = False
            ip = "?"
            try:
                ip = self._ip()
                self._dispatch(method, ip)
            except (BrokenPipeError, ConnectionResetError, socket.timeout, ssl.SSLError):
                pass
            except Exception as e:                          # never leak internals to the client
                cfg.log({"event": "error", "ip": ip, "error": "%s: %s" % (type(e).__name__, e)})
                try:
                    if not self._status:
                        self._json(500, _err("internal error", "server_error"))
                except OSError:
                    pass
            finally:
                cfg.log({"ip": ip, "m": method, "path": self.path.split("?", 1)[0][:200], "status": self._status,
                         "ms": int((time.monotonic() - self._t0) * 1000), "who": self._who, "model": self._mname})

        def do_GET(self):
            self._entry("GET")

        def do_HEAD(self):
            self._entry("HEAD")

        def do_POST(self):
            self._entry("POST")

        def do_OPTIONS(self):
            self._entry("OPTIONS")

        def do_PUT(self):
            self._entry("PUT")

        def do_DELETE(self):
            self._entry("DELETE")

        def do_PATCH(self):
            self._entry("PATCH")

        def _dispatch(self, method: str, ip: str) -> None:
            if (cfg.deny and sec.ip_in(ip, cfg.deny)) or (cfg.allow and not sec.ip_in(ip, cfg.allow)):
                return self._json(403, _err("forbidden", "invalid_request_error", "forbidden"))
            left = cfg.bans.banned(ip)
            if left:
                return self._limited(left, "temporarily blocked", "blocked")
            ok, wait = cfg.ip_limiter.allow("ip:" + ip)
            if not ok:
                return self._limited(wait, "too many requests")
            path = urlsplit(self.path).path or "/"
            if method == "OPTIONS":
                origin = (self.headers.get("Origin") or "").rstrip("/")
                allowed = cfg.cors or (origin and origin in cfg.cors_origins)
                return self._headers(204 if allowed else 405, "text/plain", 0)
            if path == "/health":
                return self._json(200, {"status": "ok", "service": "llmf"})
            if path.startswith("/_llmf/"):
                return self._internal(method, path, ip)
            if path == "/v1" or path.startswith("/v1/"):
                return self._api(method, path[3:].rstrip("/"), ip)
            if cfg.static is None and cfg.app_port is None and not cfg.ui:
                if path in ("/", ""):
                    return self._json(200, {"status": "ok", "service": "llmf"})
                if path in ("/models", "/chat/completions"):     # legacy un-prefixed form
                    return self._api(method, path, ip)
                return self._json(404, _err("not found: %s" % path, "invalid_request_error", "not_found"))
            return self._site(method, path, ip)

        # -------------------------------------------------------- /_llmf/* (sessions, assets)
        def _internal(self, method: str, path: str, ip: str) -> None:
            if path in ("/_llmf/client.js", "/_llmf/ui.js") and method in ("GET", "HEAD") and cfg.sessions:
                return self._bytes(_asset(path.rsplit("/", 1)[1]), "text/javascript; charset=utf-8")
            if not cfg.sessions or cfg.antibot is None:
                return self._json(404, _err("not found", "invalid_request_error", "not_found"))
            ab = cfg.antibot
            if path == "/_llmf/config" and method in ("GET", "HEAD"):
                return self._json(200, dict(ab.config(), session=True))
            if path == "/_llmf/challenge" and method in ("GET", "HEAD"):
                ok, wait = cfg.challenge_limiter.allow("c:" + ip)
                if not ok:
                    return self._limited(wait, "too many challenges")
                try:
                    return self._json(200, ab.challenge(ip))
                except ValueError as e:
                    return self._json(400, _err(str(e), "invalid_request_error"))
            if path == "/_llmf/session" and method == "POST":
                ok, wait = cfg.challenge_limiter.allow("c:" + ip)
                if not ok:
                    return self._limited(wait, "too many session requests")
                body = self._read_json(4096)
                if body is None:
                    return
                try:
                    out = ab.session(ip, body if isinstance(body, dict) else {})
                except PermissionError as e:
                    cfg.bans.strike(ip)
                    return self._json(403, _err(str(e), "invalid_request_error", "antibot_failed"))
                self._who = "session-new"
                return self._json(200, out)
            self._json(404, _err("not found", "invalid_request_error", "not_found"))

        def _read_json(self, limit: int) -> Any:
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(411, _err("Content-Length required", "invalid_request_error"))
                return None
            if n < 0 or n > limit:
                self._json(413, _err("request too large", "invalid_request_error"))
                return None
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError as e:
                self._json(400, _err("bad request: %s" % e, "invalid_request_error"))
                return None

        # ------------------------------------------------------------------ /v1
        def _api(self, method: str, route: str, ip: str) -> None:
            if route == "/models" and method in ("GET", "HEAD"):
                who = self._principal(ip)
                if who is None:
                    return self._deny_auth(ip)
                self._who = "%s:%s" % (who[0], who[1] if who[0] == "key" else "")
                if who[0] == "key":
                    ok, wait = cfg.key_limiter.allow("k:" + who[1])
                    if not ok:
                        return self._limited(wait, "rate limit reached, retry shortly")
                now = int(time.time())
                ids = list(ALIASES) + [m.name for m in cfg.client.models()]
                return self._json(200, {"object": "list", "data": [
                    {"id": i, "object": "model", "created": now, "owned_by": "llmf"} for i in ids]})
            if route != "/chat/completions" or method != "POST":
                return self._json(404, _err("not found: %s" % self.path, "invalid_request_error", "not_found"))
            who = self._principal(ip)
            if who is None:
                return self._deny_auth(ip)
            kind = who[0]
            self._who = "%s:%s" % (kind, who[1] if kind == "key" else "")
            if kind == "key":
                ok, wait = cfg.key_limiter.allow("k:" + who[1])
            elif kind == "session":
                ok, wait = cfg.session_limiter.allow("s:" + ip)
            else:
                ok, wait = True, 0.0
            if not ok:
                return self._limited(wait, "rate limit reached, retry shortly")
            body = self._read_json(cfg.max_body)
            if body is None:
                return
            err = self._validate(body, kind)
            if err:
                return self._json(400, _err(err, "invalid_request_error"))
            if cfg.slots is not None and not cfg.slots.acquire(blocking=False):
                return self._limited(1, "server is busy, retry shortly", "busy")
            try:
                self._chat(body, body["messages"])
            finally:
                if cfg.slots is not None:
                    cfg.slots.release()

        def _validate(self, body: Any, kind: str) -> Optional[str]:
            if not isinstance(body, dict):
                return "bad request: JSON object expected"
            msgs = body.get("messages")
            if not isinstance(msgs, list) or not msgs:
                return "bad request: messages must be a non-empty list"
            limit_msgs = {"session": 40, "key": 200}.get(kind, 1000)
            if len(msgs) > limit_msgs:
                return "too many messages (max %d)" % limit_msgs
            chars = 0
            for m in msgs:
                if not isinstance(m, dict) or not isinstance(m.get("role"), str):
                    return "bad request: every message needs a role"
                c = m.get("content")
                if isinstance(c, str):
                    chars += len(c)
                elif isinstance(c, list):
                    for part in c:
                        if not isinstance(part, dict):
                            return "bad request: malformed content part"
                        if part.get("type") == "text":
                            chars += len(str(part.get("text", "")))
                        elif kind == "session":
                            return "images are not allowed for web sessions"
                elif c is not None:
                    return "bad request: content must be a string or a list"
            if kind == "session":
                if chars > 24000:
                    return "conversation too long for a web session (max 24000 characters)"
                body.pop("tools", None)
            cap = cfg.session_max_tokens if kind == "session" else cfg.max_tokens_cap
            if cap > 0:
                for key in ("max_tokens", "max_completion_tokens"):
                    v = body.get(key)
                    if v is not None:
                        try:
                            v = int(v)
                        except (TypeError, ValueError):
                            return "max_tokens must be an integer"
                        body.pop(key, None)
                        body["max_tokens"] = min(v, cap)
            return None

        # --------------------------------------------------------------- chat
        def _model(self, requested: Any):
            if not isinstance(requested, str) or requested.strip().lower() in ("", "auto", "default"):
                return None
            try:
                cfg.client._reg.resolve(requested)
                return requested
            except ModelNotFound:
                if cfg.strict_models:
                    raise
                return None  # unknown name from a client app (e.g. "gpt-4o") -> automatic

        PARAMS = ("max_tokens", "max_completion_tokens", "temperature", "top_p", "stop", "tools",
                  "response_format")

        def _chat(self, body: dict, msgs: list) -> None:
            try:
                model = self._model(body.get("model"))
            except ModelNotFound as e:
                return self._json(404, _err(str(e), "invalid_request_error", "model_not_found"))
            kw: Dict[str, Any] = {k: body[k] for k in self.PARAMS if body.get(k) is not None}
            kw["fallback"] = True if cfg.fallback else None
            create = cfg.client.chat.completions.create
            try:
                if body.get("stream"):
                    return self._stream(create(messages=msgs, model=model, stream=True, **kw))
                comp = create(messages=msgs, model=model, **kw)
            except AllProvidersFailed as e:
                return self._json(502, _err(str(e) if not cfg.public else "all upstream providers failed",
                                            "upstream_error", "all_providers_failed"))
            except (LLMFError, ValueError) as e:
                return self._json(400, _err(str(e), "invalid_request_error"))
            self._mname = getattr(comp, "model", None)
            self._json(200, comp.to_dict())

        def _stream(self, stream) -> None:
            it = iter(stream)
            try:
                first = next(it)  # fallback between providers happens here, before any bytes
            except AllProvidersFailed as e:
                return self._json(502, _err(str(e) if not cfg.public else "all upstream providers failed",
                                            "upstream_error", "all_providers_failed"))
            except LLMFError as e:
                return self._json(400, _err(str(e), "invalid_request_error"))
            self._mname = getattr(first, "model", None)
            self._headers(200, "text/event-stream", X_Accel_Buffering="no")

            def send(obj: Any) -> None:
                self.wfile.write(b"data: " + json.dumps(obj, ensure_ascii=False).encode() + b"\n\n")
                self.wfile.flush()

            send(first.to_dict())
            try:
                for chunk in it:
                    send(chunk.to_dict())
            except LLMFError as e:
                send(_err(str(e) if not cfg.public else "upstream error", "upstream_error"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        # --------------------------------------------------------- web: ui / files / app
        def _ui_csp(self) -> str:
            ts = cfg.antibot is not None and cfg.antibot.mode == "turnstile"
            cf = " https://challenges.cloudflare.com"
            return ("default-src 'self'; script-src 'self'%s; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; frame-src%s; base-uri 'none'; "
                    "form-action 'self'; frame-ancestors 'self'" % (cf if ts else "", cf if ts else " 'none'"))

        def _site(self, method: str, path: str, ip: str) -> None:
            p = path.rstrip("/") or "/"
            show_ui = cfg.ui and (p == "/chat" or (p in ("/", "/index.html") and cfg.static is None
                                                   and cfg.app_port is None))
            if show_ui and method in ("GET", "HEAD"):
                return self._bytes(_asset("chat.html"), "text/html; charset=utf-8", csp=self._ui_csp())
            if cfg.app_port is not None:
                return self._proxy(method, ip)
            if cfg.static is not None:
                if method not in ("GET", "HEAD"):
                    return self._json(405, _err("method not allowed", "invalid_request_error"), Allow="GET, HEAD")
                f = cfg.static.find(path)
                if f is None:
                    return self._json(404, _err("not found", "invalid_request_error", "not_found"))
                return self._send_file(f)
            self._json(404, _err("not found", "invalid_request_error", "not_found"))

        def _send_file(self, f: str) -> None:
            try:
                size = os.path.getsize(f)
                fh = open(f, "rb")
            except OSError:
                return self._json(404, _err("not found", "invalid_request_error", "not_found"))
            with fh:
                self._headers(200, _web.content_type(f), size, Cache_Control="no-cache")
                if self.command == "HEAD":
                    return
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _proxy(self, method: str, ip: str) -> None:
            body = None
            if method in ("POST", "PUT", "PATCH", "DELETE") or self.headers.get("Content-Length"):
                if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                    return self._json(411, _err("chunked request bodies are not supported", "invalid_request_error"))
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._json(400, _err("bad Content-Length", "invalid_request_error"))
                if n < 0 or n > APP_MAX_BODY:
                    return self._json(413, _err("request too large", "invalid_request_error"))
                body = self.rfile.read(n) if n else b""
            self._proxied = True
            self._who = "app"
            _web.proxy_request(self, cfg.app_port, method=method, body=body, client_ip=ip,
                               scheme=self._scheme(), drop_auth=self._is_credential)

    return Handler


def make_server(client: Client, host: str = "127.0.0.1", port: int = 8000, **opts: Any) -> ThreadingHTTPServer:
    """Build (but do not run) the server. See ``_DEFAULTS`` for the options (``llmf serve --help`` lists the flags)."""
    cfg = _Config(client, opts)
    srv = _Server((host, port), make_handler(cfg))
    srv.cfg = cfg
    if cfg.public:
        srv.conn_slots = threading.BoundedSemaphore(int(opts.get("max_connections") or 256))
    if opts.get("tls_cert"):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(opts["tls_cert"], opts.get("tls_key") or None)
        srv.ssl_context = ctx
    return srv


def _say(msg: str = "") -> None:
    print(msg, file=sys.stderr)


def serve(client: Client, host: str = "127.0.0.1", port: int = 8000, *, cloudflare: bool = False,
          tunnel_token: Optional[str] = None, app: Optional[str] = None, app_dir: Optional[str] = None,
          **kw: Any) -> None:
    """Run the server until Ctrl+C, together with the optional child app and Cloudflare tunnel."""
    from ._tunnel import Tunnel, TunnelError

    tunnelled = bool(cloudflare or tunnel_token)
    if tunnelled:
        kw["public"] = True            # reachable from the internet: use the hardening profile
        kw["trust_proxy"] = True       # cloudflared connects from loopback and sends CF-Connecting-IP
    if app and not kw.get("app_port"):
        kw["app_port"] = 3000
    srv = make_server(client, host, port, **kw)
    cfg: _Config = srv.cfg
    h, p = srv.server_address[:2]
    scheme = "https" if cfg.tls else "http"
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    child = tunnel = None
    public_url = None
    try:
        if app:
            key = cfg.api_keys[0] if cfg.api_keys else "llmf-local"
            base = "http://127.0.0.1:%s/v1" % p if not cfg.tls else "https://127.0.0.1:%s/v1" % p
            child = _web.AppProcess(app, int(cfg.app_port), cwd=app_dir, env={
                "LLMF_BASE_URL": base, "OPENAI_BASE_URL": base, "OPENAI_API_KEY": key, "LLMF_API_KEY": key})
            child.start()
        if tunnelled:
            tunnel = Tunnel(int(p), token=tunnel_token, scheme=scheme)
            public_url = tunnel.start()
    except (RuntimeError, ValueError, TunnelError) as e:
        srv.shutdown()
        srv.server_close()
        if child:
            child.stop()
        raise SystemExit("error: %s" % e)

    shown = "127.0.0.1" if h in ("0.0.0.0", "::") else h
    _say("llmf serving on %s://%s:%s  (Ctrl+C to stop)" % (scheme, shown, p))
    _say("  API        %s://%s:%s/v1" % (scheme, shown, p))
    if cfg.ui:
        _say("  chat UI    %s://%s:%s/%s" % (scheme, shown, p, "chat" if (cfg.static or cfg.app_port) else ""))
    if cfg.static:
        _say("  web        %s" % cfg.static.describe())
    if app:
        _say("  app        %s  (port %s)" % (app, cfg.app_port))
    if public_url:
        _say("  public     %s" % public_url)
    elif tunnel_token:
        _say("  public     (named tunnel running: use the hostname you configured in Cloudflare)")
    if host not in ("127.0.0.1", "localhost", "::1") or tunnelled or cfg.public:
        if cfg.generated_key:
            _say("  api key    %s   (generated for this run; pass --api-key to choose your own)" % cfg.generated_key)
        _say("  security   auth %s | rate %s/min per key, %s/min per IP | ban after %s auth failures | "
             "antibot %s" % ("required" if cfg.require_auth else "off", cfg.key_limiter.rate * 60 or "off",
                              cfg.ip_limiter.rate * 60 or "off", cfg.bans.after or "off",
                              cfg.antibot.mode if cfg.antibot else "-"))
        if host == "0.0.0.0" and not cfg.tls and not tunnelled:
            _say("  note       plain HTTP on all interfaces: put it behind HTTPS (--cloudflare, a reverse proxy, "
                 "or --tls-cert/--tls-key) before sharing it")
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel:
            tunnel.stop()
        if child:
            child.stop()
        srv.shutdown()
        srv.server_close()
        cfg.close()
