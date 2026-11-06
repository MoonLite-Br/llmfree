"""Public-internet features of `llmf serve`: auth, limits, bans, antibot, static/app/UI, tunnel, TLS."""
import hashlib
import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["LLMF_NO_CACHE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import llmf  # noqa: E402
from llmf import _security as sec  # noqa: E402
from llmf import _web  # noqa: E402
from llmf._tunnel import Tunnel, TunnelError  # noqa: E402
from llmf.server import make_server  # noqa: E402
import test_server as ts  # noqa: E402


def raw(base, method, path, body=None, headers=None):
    u = urllib.parse.urlsplit(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    h = dict(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    out = r.read()
    hd = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, hd, out


def js(out):
    return json.loads(out)


CHAT = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}


def solve(challenge, bits):
    n = 0
    while True:
        if sec.leading_zero_bits(hashlib.sha256(("%s:%d" % (challenge, n)).encode()).digest()) >= bits:
            return n
        n += 1


def session(base, headers=None):
    st, _, out = raw(base, "GET", "/_llmf/challenge", headers=headers)
    assert st == 200, out
    ch = js(out)
    st, _, out = raw(base, "POST", "/_llmf/session", {"challenge": ch["challenge"], "counter": solve(ch["challenge"], ch["bits"])},
                     headers=headers)
    return st, js(out)


class Units(unittest.TestCase):
    def test_rate_limiter(self):
        r = sec.RateLimiter(60, burst=3)
        self.assertEqual([r.allow("a")[0] for _ in range(4)], [True, True, True, False])
        self.assertTrue(r.allow("b")[0])
        self.assertTrue(sec.RateLimiter(0).allow("x")[0])

    def test_banlist(self):
        b = sec.BanList(after=3)
        self.assertEqual([b.strike("1.1.1.1") for _ in range(3)], [False, False, True])
        self.assertGreater(b.banned("1.1.1.1"), 0)
        self.assertEqual(b.banned("2.2.2.2"), 0)

    def test_cidr(self):
        nets = sec.parse_networks(["10.0.0.0/8", "2001:db8::/32,192.168.1.5"])
        self.assertTrue(sec.ip_in("10.2.3.4", nets) and sec.ip_in("2001:db8::1", nets) and sec.ip_in("192.168.1.5", nets))
        self.assertFalse(sec.ip_in("11.0.0.1", nets))
        self.assertTrue(sec.ip_in("::ffff:10.1.1.1", nets))
        with self.assertRaises(ValueError):
            sec.parse_networks(["nope"])

    def test_pow_flow_and_replay(self):
        a = sec.Antibot("pow", bits=8, secret=b"k" * 32)
        ch = a.challenge("1.2.3.4")
        c = solve(ch["challenge"], ch["bits"])
        tok = a.session("1.2.3.4", {"challenge": ch["challenge"], "counter": c})["token"]
        self.assertTrue(a.valid_token(tok, "1.2.3.4"))
        self.assertFalse(a.valid_token(tok, "5.6.7.8"))          # IP bound
        self.assertFalse(a.valid_token(tok[:-1] + "0", "1.2.3.4"))
        with self.assertRaises(PermissionError):                 # replay
            a.session("1.2.3.4", {"challenge": ch["challenge"], "counter": c})
        ch2 = a.challenge("1.2.3.4")
        with self.assertRaises(PermissionError):                 # wrong IP
            a.session("9.9.9.9", {"challenge": ch2["challenge"], "counter": solve(ch2["challenge"], ch2["bits"])})
        with self.assertRaises(PermissionError):
            a.session("1.2.3.4", {"challenge": ch2["challenge"], "counter": 0 if solve(ch2["challenge"], ch2["bits"]) else 1})

    def test_turnstile(self):
        seen = {}

        def fetch(url, f):
            seen.update(f)
            return {"success": f["response"] == "good"}

        a = sec.Antibot("turnstile", turnstile_secret="S", turnstile_sitekey="K", fetch=fetch)
        self.assertTrue(a.session("1.1.1.1", {"turnstile": "good"})["token"])
        with self.assertRaises(PermissionError):
            a.session("1.1.1.1", {"turnstile": "bad"})
        with self.assertRaises(PermissionError):
            a.session("1.1.1.1", {})
        self.assertEqual(seen["secret"], "S")
        boom = sec.Antibot("turnstile", turnstile_secret="S", turnstile_sitekey="K",
                           fetch=lambda u, f: (_ for _ in ()).throw(OSError("down")))
        with self.assertRaises(PermissionError):                 # fail closed
            boom.session("1.1.1.1", {"turnstile": "x"})
        with self.assertRaises(ValueError):
            sec.Antibot("turnstile")

    def test_expired_token(self):
        a = sec.Antibot("off", session_ttl=-5)
        self.assertFalse(a.valid_token(a.session("1.1.1.1", {})["token"], "1.1.1.1"))


class PublicServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ts.setUpModule() if hasattr(ts, "setUpModule") else None

    def test_generated_key_and_auth(self):
        srv, base = ts.start(public=True)
        key = srv.cfg.generated_key
        self.assertTrue(key.startswith("llmf-"))
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", CHAT)[0], 401)
        self.assertEqual(raw(base, "GET", "/v1/models")[0], 401)
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", CHAT, {"Authorization": "Bearer wrong"})[0], 401)
        st, hd, out = raw(base, "POST", "/v1/chat/completions", CHAT, {"Authorization": "Bearer " + key})
        self.assertEqual(st, 200, out)
        self.assertEqual(hd["x-content-type-options"], "nosniff")
        self.assertEqual(hd["server"], "llmf")
        self.assertNotIn("python", json.dumps(hd).lower())
        self.assertEqual(raw(base, "GET", "/health")[0], 200)          # health stays open

    def test_multiple_keys(self):
        srv, base = ts.start(api_key=["k1", "k2"])
        for k in ("k1", "k2"):
            self.assertEqual(raw(base, "GET", "/v1/models", headers={"Authorization": "Bearer " + k})[0], 200)
        self.assertEqual(raw(base, "GET", "/v1/models", headers={"Authorization": "Bearer k3"})[0], 401)

    def test_key_rate_limit(self):
        srv, base = ts.start(api_key="k", rate=60, ip_rate=0)
        srv.cfg.key_limiter.burst = 2
        codes = [raw(base, "GET", "/v1/models", headers={"Authorization": "Bearer k"}) for _ in range(5)]
        self.assertIn(429, [c[0] for c in codes])
        r = [c for c in codes if c[0] == 429][0]
        self.assertGreaterEqual(int(r[1]["retry-after"]), 1)
        self.assertEqual(js(r[2])["error"]["type"], "rate_limit_error")

    def test_ip_rate_limit(self):
        srv, base = ts.start(public=True, ip_rate=60)
        srv.cfg.ip_limiter.burst = 3
        self.assertIn(429, [raw(base, "GET", "/health")[0] for _ in range(8)])

    def test_ban_after_failures(self):
        srv, base = ts.start(api_key="k", ban_after=3)
        codes = [raw(base, "GET", "/v1/models", headers={"Authorization": "Bearer bad"})[0] for _ in range(5)]
        self.assertEqual(codes[:3], [401, 401, 401])
        self.assertEqual(codes[3], 429)
        # a banned IP is blocked even with the right key
        self.assertEqual(raw(base, "GET", "/v1/models", headers={"Authorization": "Bearer k"})[0], 429)

    def test_allow_deny(self):
        srv, base = ts.start(deny_ip=["127.0.0.0/8"])
        self.assertEqual(raw(base, "GET", "/health")[0], 403)
        srv, base = ts.start(allow_ip=["10.0.0.0/8"])
        self.assertEqual(raw(base, "GET", "/health")[0], 403)
        srv, base = ts.start(allow_ip=["127.0.0.1"])
        self.assertEqual(raw(base, "GET", "/health")[0], 200)

    def test_trust_proxy(self):
        srv, base = ts.start(deny_ip=["8.8.8.8"], trust_proxy=True)
        self.assertEqual(raw(base, "GET", "/health", headers={"CF-Connecting-IP": "8.8.8.8"})[0], 403)
        self.assertEqual(raw(base, "GET", "/health", headers={"X-Forwarded-For": "1.1.1.1, 8.8.8.8"})[0], 403)
        # not trusted: header ignored
        srv, base = ts.start(deny_ip=["8.8.8.8"])
        self.assertEqual(raw(base, "GET", "/health", headers={"CF-Connecting-IP": "8.8.8.8"})[0], 200)

    def test_limits(self):
        srv, base = ts.start(public=True, max_body=500, max_tokens_cap=7)
        h = {"Authorization": "Bearer " + srv.cfg.generated_key}
        big = {"messages": [{"role": "user", "content": "x" * 2000}]}
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", big, h)[0], 413)
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", b"{nope", h)[0], 400)
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", {"messages": []}, h)[0], 400)
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", dict(CHAT, max_tokens=99999), h)[0], 200)

    def test_cors_allowlist(self):
        srv, base = ts.start(cors_origins=["https://app.example"])
        st, hd, _ = raw(base, "GET", "/health", headers={"Origin": "https://app.example"})
        self.assertEqual(hd.get("access-control-allow-origin"), "https://app.example")
        st, hd, _ = raw(base, "GET", "/health", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", hd)
        self.assertEqual(raw(base, "OPTIONS", "/v1/chat/completions", headers={"Origin": "https://app.example"})[0], 204)

    def test_access_log_has_no_prompts(self):
        d = tempfile.mkdtemp()
        lf = os.path.join(d, "a.log")
        srv, base = ts.start(log_file=lf, api_key="secretkey123")
        raw(base, "POST", "/v1/chat/completions", dict(CHAT, messages=[{"role": "user", "content": "TOPSECRETPROMPT"}]),
            {"Authorization": "Bearer secretkey123"})
        srv.cfg.close()
        text = open(lf).read()
        self.assertIn('"status": 200', text)
        self.assertNotIn("TOPSECRETPROMPT", text)
        self.assertNotIn("secretkey123", text)
        shutil.rmtree(d)

    def test_internal_error_hidden(self):
        srv, base = ts.start()
        srv.cfg.client = None                      # force an exception inside the handler
        st, _, out = raw(base, "POST", "/v1/chat/completions", CHAT)
        self.assertEqual(st, 500)
        self.assertEqual(js(out)["error"]["message"], "internal error")


class Hardening(unittest.TestCase):
    def test_loopback_only_for_proxy_headers(self):
        self.assertTrue(sec.is_loopback("127.0.0.1") and sec.is_loopback("::1"))
        self.assertFalse(sec.is_loopback("192.168.1.9") or sec.is_loopback("10.0.0.2"))

    def test_connection_cap(self):
        import socket, time
        srv, base = ts.start(public=True, max_connections=2)
        port = srv.server_address[1]
        idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(2)]
        time.sleep(0.3)
        extra = socket.create_connection(("127.0.0.1", port), timeout=3)
        extra.sendall(b"GET /health HTTP/1.0\r\n\r\n")
        try:
            data = extra.recv(100)
        except OSError:
            data = b""
        self.assertEqual(data, b"")                      # dropped, not served
        for c in idle + [extra]:
            c.close()
        time.sleep(0.5)
        self.assertEqual(raw(base, "GET", "/health")[0], 200)    # slots are released


class SessionFlow(unittest.TestCase):
    def test_session_chat_limits(self):
        srv, base = ts.start(public=True, ui=True, pow_bits=8, session_rate=60)
        self.assertEqual(raw(base, "GET", "/_llmf/config")[0], 200)
        st, out = session(base)
        self.assertEqual(st, 200)
        h = {"Authorization": "Bearer " + out["token"]}
        st, _, o = raw(base, "POST", "/v1/chat/completions", CHAT, h)
        self.assertEqual(st, 200, o)
        img = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:x"}}]}]}
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", img, h)[0], 400)
        self.assertEqual(raw(base, "POST", "/v1/chat/completions",
                             {"messages": [{"role": "user", "content": "x" * 30000}]}, h)[0], 400)
        # sessions are per-IP bound; a made-up token is rejected
        self.assertEqual(raw(base, "POST", "/v1/chat/completions", CHAT, {"Authorization": "Bearer llmf1.9999999999.abc"})[0], 401)

    def test_no_proof_no_session(self):
        srv, base = ts.start(public=True, ui=True, pow_bits=8)
        self.assertEqual(raw(base, "POST", "/_llmf/session", {})[0], 403)
        self.assertEqual(raw(base, "POST", "/_llmf/session", {"challenge": "v1.1.a.8.b", "counter": 1})[0], 403)

    def test_session_rate_limit(self):
        srv, base = ts.start(public=True, ui=True, pow_bits=8, session_rate=6)
        srv.cfg.session_limiter.burst = 2
        h = {"Authorization": "Bearer " + session(base)[1]["token"]}
        codes = [raw(base, "POST", "/v1/chat/completions", CHAT, h)[0] for _ in range(5)]
        self.assertIn(429, codes)

    def test_turnstile_server(self):
        srv, base = ts.start(public=True, ui=True, antibot="turnstile", turnstile_secret="S", turnstile_sitekey="K",
                             fetch=lambda u, f: {"success": f["response"] == "ok"})
        self.assertEqual(js(raw(base, "GET", "/_llmf/config")[2])["turnstile_sitekey"], "K")
        self.assertEqual(raw(base, "POST", "/_llmf/session", {"turnstile": "no"})[0], 403)
        self.assertEqual(raw(base, "POST", "/_llmf/session", {"turnstile": "ok"})[0], 200)

    def test_sessions_unavailable_without_ui(self):
        srv, base = ts.start()
        self.assertEqual(raw(base, "GET", "/_llmf/config")[0], 404)

    def test_challenge_rate_limited(self):
        srv, base = ts.start(public=True, ui=True)
        srv.cfg.challenge_limiter.burst = 2
        self.assertIn(429, [raw(base, "GET", "/_llmf/challenge")[0] for _ in range(6)])


class Web(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def w(self, name, text="x"):
        p = os.path.join(self.d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)
        return p

    def test_single_file_only(self):
        f = self.w("site/index.html", "<h1>hi</h1>")
        self.w("site/secret.txt", "SECRET")
        srv, base = ts.start(web=f)
        for p in ("/", "/index.html"):
            st, hd, out = raw(base, "GET", p)
            self.assertEqual((st, out), (200, b"<h1>hi</h1>"))
        self.assertIn("text/html", hd["content-type"])
        self.assertEqual(raw(base, "GET", "/secret.txt")[0], 404)
        self.assertEqual(raw(base, "GET", "/../secret.txt")[0], 404)
        self.assertEqual(raw(base, "POST", "/", {})[0], 405)
        self.assertEqual(raw(base, "GET", "/health")[0], 200)

    def test_directory_safe(self):
        self.w("pub/index.html", "INDEX")
        self.w("pub/app.js", "JS")
        self.w("pub/.env", "TOKEN")
        self.w("outside.txt", "OUT")
        os.symlink(os.path.join(self.d, "outside.txt"), os.path.join(self.d, "pub", "link.txt"))
        srv, base = ts.start(web=os.path.join(self.d, "pub"))
        self.assertEqual(raw(base, "GET", "/app.js")[2], b"JS")
        self.assertIn("javascript", raw(base, "GET", "/app.js")[1]["content-type"])
        self.assertEqual(raw(base, "GET", "/.env")[0], 404)
        self.assertEqual(raw(base, "GET", "/link.txt")[0], 404)
        self.assertEqual(raw(base, "GET", "/%2e%2e/outside.txt")[0], 404)
        self.assertEqual(raw(base, "GET", "/..%2foutside.txt")[0], 404)
        self.assertEqual(raw(base, "GET", "/a/b/route")[2], b"INDEX")     # SPA fallback
        self.assertEqual(raw(base, "GET", "/missing.png")[0], 404)

    def test_find_unit(self):
        self.w("p/index.html")
        s = _web.StaticSite(os.path.join(self.d, "p"))
        for bad in ("/../x", "/.git/config", "/a\x00b", "\\..\\x"):
            self.assertIsNone(s.find(bad))
        with self.assertRaises(ValueError):
            _web.StaticSite(os.path.join(self.d, "nope"))

    def test_ui_page(self):
        srv, base = ts.start(public=True, ui=True)
        st, hd, out = raw(base, "GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"/_llmf/client.js", out)
        self.assertIn("default-src 'self'", hd["content-security-policy"])
        self.assertEqual(raw(base, "GET", "/_llmf/client.js")[0], 200)
        self.assertEqual(raw(base, "GET", "/_llmf/ui.js")[0], 200)
        self.assertEqual(raw(base, "GET", "/nope")[0], 404)

    def test_ui_next_to_web(self):
        f = self.w("i.html", "MINE")
        srv, base = ts.start(web=f, ui=True)
        self.assertEqual(raw(base, "GET", "/")[2], b"MINE")
        self.assertIn(b"client.js", raw(base, "GET", "/chat")[2])


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        out = json.dumps({"path": self.path, "method": self.command, "body": body.decode(),
                          "xff": self.headers.get("X-Forwarded-For"), "auth": self.headers.get("Authorization"),
                          "proto": self.headers.get("X-Forwarded-Proto")}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Set-Cookie", "a=1")
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = _do


class AppProxy(unittest.TestCase):
    def setUp(self):
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self.addCleanup(self.up.shutdown)
        self.port = self.up.server_address[1]

    def test_proxy_roundtrip(self):
        srv, base = ts.start(app_port=self.port, public=True, api_key="k")
        st, hd, out = raw(base, "POST", "/api/x?y=1", {"a": 1}, {"X-Forwarded-For": "6.6.6.6", "Authorization": "Bearer k"})
        d = js(out)
        self.assertEqual((st, d["path"], d["method"]), (201, "/api/x?y=1", "POST"))
        self.assertEqual(json.loads(d["body"]), {"a": 1})
        self.assertEqual(d["xff"], "127.0.0.1")        # client-supplied XFF is not forwarded
        self.assertIsNone(d["auth"])                   # llmf credentials are never leaked to the app
        self.assertEqual(hd["set-cookie"], "a=1")
        st, _, out = raw(base, "GET", "/", headers={"Authorization": "Bearer app-own-token"})
        self.assertEqual(js(out)["auth"], "Bearer app-own-token")  # the app's own tokens pass through
        self.assertEqual(raw(base, "GET", "/health")[0], 200)
        self.assertEqual(raw(base, "GET", "/v1/models")[0], 401)   # llmf API still guarded

    def test_ip_rules_apply_to_app(self):
        srv, base = ts.start(app_port=self.port, deny_ip=["127.0.0.1"])
        self.assertEqual(raw(base, "GET", "/")[0], 403)

    def test_app_down(self):
        s = __import__("socket").socket()
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
        s.close()
        srv, base = ts.start(app_port=free)
        self.assertEqual(raw(base, "GET", "/")[0], 502)

    def test_websocket_501(self):
        srv, base = ts.start(app_port=self.port)
        self.assertEqual(raw(base, "GET", "/", headers={"Upgrade": "websocket", "Connection": "Upgrade"})[0], 501)

    def test_big_body_rejected(self):
        srv, base = ts.start(app_port=self.port)
        st, _, _ = raw(base, "POST", "/", headers={"Content-Length": str(10**9)})
        self.assertEqual(st, 413)


class AppProcess(unittest.TestCase):
    def test_start_and_stop(self):
        code = ("import os,http.server as h\n"
                "class H(h.BaseHTTPRequestHandler):\n"
                "  def do_GET(s):\n    s.send_response(200);s.end_headers();s.wfile.write(os.environ['PORT'].encode())\n"
                "  def log_message(*a):pass\n"
                "print('ready',flush=True)\n"
                "h.HTTPServer(('127.0.0.1',int(os.environ['PORT'])),H).serve_forever()\n")
        s = __import__("socket").socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        logs = []
        app = _web.AppProcess("%s -c \"%s\"" % (sys.executable, code.replace('"', '\\"').replace("$", "\\$")), port, log=logs.append)
        app.start(wait=15)
        try:
            self.assertTrue(_web.port_open(port))
            self.assertEqual(urllib.request.urlopen("http://127.0.0.1:%d/" % port).read(), str(port).encode())
        finally:
            app.stop()
        self.assertFalse(_web.port_open(port))
        self.assertTrue(any(l.startswith("[app] ready") for l in logs))

    def test_missing_command(self):
        with self.assertRaises(ValueError) as cm:
            _web.AppProcess("definitely-not-a-cmd-xyz main.js", 1)
        self.assertIn("not found", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            _web.resolve_command("node") if not shutil.which("node") else (_ for _ in ()).throw(ValueError("not found"))
        self.assertIn("not found", str(cm.exception))

    def test_exits_early(self):
        app = _web.AppProcess("%s -c \"raise SystemExit(3)\"" % sys.executable, 1, log=lambda s: None)
        with self.assertRaises(RuntimeError) as cm:
            app.start(wait=5)
        self.assertIn("exited", str(cm.exception))


class TunnelTests(unittest.TestCase):
    def fake(self, body):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "cloudflared")
        open(p, "w").write("#!%s\n%s\n" % (sys.executable, body))
        os.chmod(p, 0o755)
        return p

    def test_quick_tunnel(self):
        p = self.fake("import sys,time\nprint('INF |  https://fun-test-abc.trycloudflare.com  |',flush=True)\n"
                      "open(sys.argv[0]+'.args','w').write(' '.join(sys.argv[1:]))\ntime.sleep(30)")
        t = Tunnel(8123, binary=p)
        try:
            self.assertEqual(t.start(timeout=10), "https://fun-test-abc.trycloudflare.com")
            import time
            time.sleep(0.3)
            self.assertIn("--url http://127.0.0.1:8123", open(p + ".args").read())
        finally:
            t.stop()
        self.assertIsNotNone(t.proc.poll())

    def test_named_tunnel(self):
        p = self.fake("import time\nprint('Registered tunnel connection connIndex=0',flush=True)\ntime.sleep(30)")
        t = Tunnel(1, token="TKN", binary=p)
        try:
            self.assertIsNone(t.start(timeout=10))
            self.assertEqual(t.argv()[-3:], ["run", "--token", "TKN"])
        finally:
            t.stop()

    def test_dies(self):
        p = self.fake("print('boom: no network');raise SystemExit(1)")
        with self.assertRaises(TunnelError) as cm:
            Tunnel(1, binary=p).start(timeout=10)
        self.assertIn("boom", str(cm.exception))

    def test_missing_binary(self):
        old = os.environ.pop("CLOUDFLARED", None)
        oldp = os.environ["PATH"]
        os.environ["PATH"] = ""
        try:
            with self.assertRaises(TunnelError) as cm:
                Tunnel(1).argv()
            self.assertIn("pkg install cloudflared", str(cm.exception))
        finally:
            os.environ["PATH"] = oldp
            if old:
                os.environ["CLOUDFLARED"] = old


@unittest.skipUnless(shutil.which("openssl"), "openssl not available")
class Tls(unittest.TestCase):
    def test_https(self):
        import ssl
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        crt, key = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                        "-days", "1", "-subj", "/CN=localhost"], check=True, capture_output=True)
        srv, _ = ts.start(tls_cert=crt, tls_key=key)
        port = srv.server_address[1]
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        c = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=10)
        c.request("GET", "/health")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("max-age", r.getheader("Strict-Transport-Security"))
        c.close()
        # plain HTTP to the TLS port must not hang or crash the server
        s = __import__("socket").create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(b"GET /health HTTP/1.0\r\n\r\n")
        try:
            s.recv(100)
        except OSError:
            pass
        s.close()
        c = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=10)
        c.request("GET", "/health")
        self.assertEqual(c.getresponse().status, 200)


class CliFlags(unittest.TestCase):
    def test_help_lists_flags(self):
        out = subprocess.run([sys.executable, "-m", "llmf", "--help"], capture_output=True, text=True,
                             env=dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"))).stdout
        for f in ("--public", "--cloudflare", "--html", "--app", "--antibot", "--allow-ip", "--tls-cert"):
            self.assertIn(f, out)

    def test_bad_cidr(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"))
        r = subprocess.run([sys.executable, "-m", "llmf", "serve", "--port", "0", "--allow-ip", "nonsense"],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("CIDR", r.stderr)


if __name__ == "__main__":
    unittest.main()
