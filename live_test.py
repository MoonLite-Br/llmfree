#!/usr/bin/env python3
"""llmf live test: exercises EVERYTHING against the real internet and writes a JSON report.

    python live_test.py                      # full run (~3-6 min; makes ~60-100 small requests)
    python live_test.py --quick              # skip the slow / per-provider extras
    python live_test.py --proxy socks5://127.0.0.1:1080
    python live_test.py --only providers,stream,server
    python live_test.py --all-models         # doctor also tests models found live (/models)
    python live_test.py --include-chatai --include-langchain --include-discover

Works with an installed llmf (pip install llmf) or straight from the repo (uses ./src).
Result: a table in the terminal and ./llmf_live_report.json  (send that file back to the author).
Exit code 1 only if a CORE (library-logic) check fails; provider outages are reported but not fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import llmf  # noqa: F401
except ImportError:  # running inside the repo without installing
    sys.path.insert(0, os.path.join(HERE, "src"))
    import llmf  # noqa: F401

from llmf import LLMF, AllProvidersFailed, ModelNotFound  # noqa: E402

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
GROUPS = ["env", "providers", "api", "stream", "vision", "resilience", "proxy", "async",
          "server", "cli", "cache", "extras"]
COLORS = {PASS: "\033[32m", FAIL: "\033[31m", WARN: "\033[33m", SKIP: "\033[90m"}


class Skip(Exception):
    pass


class Warn(Exception):
    pass


class Ctx:
    def __init__(self, args):
        self.args = args
        self.proxy = args.proxy
        self.extra = {}      # extra data stored in the report
        self.doctor = []     # results of the model sweep

    def client(self, **kw):
        kw.setdefault("timeout", self.args.timeout)
        kw.setdefault("deadline", self.args.timeout * 3)
        kw.setdefault("use_cache", False)
        if self.proxy:
            kw.setdefault("proxy", self.proxy)
        return LLMF(**kw)


CHECKS = []   # (group, name, kind, slow, fn)


def check(group, name, kind="core", slow=False):
    def deco(fn):
        CHECKS.append((group, name, kind, slow, fn))
        return fn
    return deco


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def one_line(s, n=110):
    return " ".join(str(s).split())[:n]


def provider_names():
    c = LLMF(use_cache=False)
    return [(p.name, p.default_model) for p in c.providers.list()], c


PROVIDERS, _PROBE = provider_names()
LIMITED = {"chatai"}


def make_png(w=96, h=96, rgb=(220, 20, 20)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ======================================================================= env
@check("env", "environment")
def _env(ctx):
    ctx.extra["python"] = sys.version.split()[0]
    ctx.extra["platform"] = platform.platform()
    ctx.extra["llmf"] = llmf.__version__
    return "python %s, llmf %s, %s" % (ctx.extra["python"], llmf.__version__, platform.system())


@check("env", "internet + TLS reachable (OVH /v1/models)")
def _net(ctx):
    from llmf import _http
    t0 = time.time()
    resp = _http.open_url("https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/models",
                          headers={"User-Agent": _http.DEFAULT_UA}, timeout=ctx.args.timeout, proxy=ctx.proxy)
    body = _http.decode_body(resp)
    resp.close()
    need(len(body) > 2, "empty body")
    return "HTTP ok in %.2fs" % (time.time() - t0)


@check("env", "catalogue sanity (offline)")
def _cat(ctx):
    c = ctx.client()
    ms = c.models.list()
    need(len(ms) >= 20, "catalogue too small")
    for tag in ("fast", "best", "code", "vision", "reasoning"):
        need(c.models.resolve(tag), "tag %s resolves to nothing" % tag)
    return "%d models, %d providers" % (len(ms), len(c.providers.list()))


# ================================================================== providers
@check("providers", "doctor: call every catalogued model once", kind="provider")
def _doctor(ctx):
    c = ctx.client(timeout=min(ctx.args.timeout, 30))
    lines = []

    def show(r):
        lines.append(r)
        print("      %-4s %-62s %6.2fs  %s" % ("ok" if r.ok else "FAIL", r.name, r.latency,
                                                one_line((r.answer if r.ok else r.error) or "", 60)), flush=True)

    res = c.models.check(include_live=ctx.args.all_models, include_limited=ctx.args.include_chatai, on_result=show)
    ctx.doctor = res
    ok = [r for r in res if r.ok]
    need(ok, "no model answered at all")
    ctx.extra["models"] = [{"name": r.name, "ok": r.ok, "latency": round(r.latency, 3),
                            "answer": r.answer, "error": r.error, "verified": r.verified} for r in res]
    bad = [r.name for r in res if not r.ok]
    if bad:
        raise Warn("%d/%d models answered; failing: %s" % (len(ok), len(res), ", ".join(bad[:6]) + (" ..." if len(bad) > 6 else "")))
    return "%d/%d models answered" % (len(ok), len(res))


def _provider_chat(name, model):
    @check("providers", "chat via %s (%s)" % (name, model), kind="provider")
    def _fn(ctx):
        if name in LIMITED and not ctx.args.include_chatai:
            raise Skip("quota-limited (use --include-chatai)")
        c = ctx.client()
        r = c.chat("Reply with exactly: pong", provider=name, model=model, fallback=False, max_tokens=300)
        need(r.text, "empty")
        need(r.provider == name, "answered by %s" % r.provider)
        need("<think>" not in r.text, "<think> tag leaked into answer")
        return "%.2fs  %r" % (r.latency, one_line(r.text, 60))


for _n, _m in PROVIDERS:
    _provider_chat(_n, _m)


# ====================================================================== api
@check("api", "llmf.chat() shorthand returns a str with metadata")
def _short(ctx):
    r = ctx.client().chat("What is the capital of Vietnam? Answer in one short sentence.")
    need(isinstance(r, str) and r.strip(), "not a non-empty str")
    need(r.provider and r.model, "missing provider/model")
    ctx.extra["sample_answer"] = one_line(r, 120)
    return "%s  %r" % (r.source, one_line(r, 70))


@check("api", "Vietnamese round-trip keeps diacritics")
def _vi(ctx):
    r = ctx.client().chat("Thủ đô của Việt Nam là gì? Trả lời một câu ngắn bằng tiếng Việt.")
    low = r.text.lower()
    need("hà nội" in low or "ha noi" in low or "hanoi" in low, "no Hanoi in %r" % one_line(r))
    if "hà nội" not in low:
        raise Warn("answered without diacritics: %r" % one_line(r, 70))
    return one_line(r, 80)


@check("api", "chat.completions.create() is OpenAI-shaped")
def _sdk(ctx):
    c = ctx.client()
    r = c.chat.completions.create(
        messages=[{"role": "system", "content": "Answer with one word."},
                  {"role": "user", "content": "Opposite of hot?"}], temperature=0.2, max_tokens=300)
    need(r.object == "chat.completion" and r.choices[0].message.role == "assistant", "bad shape")
    need(r.output_text == r.choices[0].message.content and r.output_text, "no content")
    d = r.to_dict()
    need(set(d) >= {"id", "object", "created", "model", "choices", "usage"}, "to_dict keys")
    return "%s  %r  usage=%s" % (r.model, one_line(r.output_text, 40), r.usage.total_tokens)


@check("api", "system prompt is honoured")
def _sys(ctx):
    r = ctx.client().chat("Say hello.", system="You must reply with the single word PINEAPPLE and nothing else.",
                          max_tokens=300)
    if "pineapple" not in r.text.lower():
        raise Warn("system prompt ignored by %s: %r" % (r.source, one_line(r, 60)))
    return r.source


@check("api", "multi-turn session remembers context")
def _sess(ctx):
    s = ctx.client().session(system="Be brief.")
    s("My name is Zorblax. Remember it.")
    r = s("What is my name?")
    need(len(s.history) == 4, "history not kept")
    if "zorblax" not in r.text.lower():
        raise Warn("%s forgot the name: %r" % (r.source, one_line(r, 60)))
    return r.source


@check("api", "JSON mode returns parseable JSON")
def _json(ctx):
    r = ctx.client().chat('Return a JSON object with keys "city" and "country" for Hanoi. JSON only.', json=True,
                          max_tokens=400)
    txt = r.text.strip()
    if txt.startswith("```"):
        txt = txt.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        obj = json.loads(txt)
    except ValueError:
        raise Warn("%s did not return pure JSON: %r" % (r.source, one_line(r, 70)))
    need(isinstance(obj, dict), "not an object")
    return "%s  %s" % (r.source, obj)


@check("api", "max_tokens is respected (short answer)")
def _maxtok(ctx):
    r = ctx.client().chat("Write a very long essay about the history of the Internet.", model="fast", max_tokens=40)
    n = len(r.text.split())
    need(n < 120, "answer has %d words despite max_tokens=40" % n)
    return "%d words from %s" % (n, r.source)


@check("api", "long prompt (~6k chars) works", slow=True)
def _long(ctx):
    text = ("The quick brown fox jumps over the lazy dog. " * 130)
    r = ctx.client().chat(text + "\nHow many times does the word 'fox' appear? Reply with just a number.",
                          max_tokens=400)
    need(r.text, "empty")
    return "%s  %r" % (r.source, one_line(r, 50))


@check("api", "aliases fast / best / code / reasoning each answer")
def _tags(ctx):
    c = ctx.client()
    out, bad = [], []
    for tag in ("fast", "best", "code", "reasoning"):
        try:
            r = c.chat("Say OK.", model=tag, max_tokens=400)
            out.append("%s->%s(%.1fs)" % (tag, r.source, r.latency))
        except AllProvidersFailed as e:
            bad.append(tag)
    if bad:
        raise Warn("failed: %s; ok: %s" % (bad, ", ".join(out)))
    return "; ".join(out)


@check("api", "reasoning model: <think>/reasoning stripped from answer")
def _reason(ctx):
    r = ctx.client().chat("What is 17 * 23? Give just the number.", model="reasoning", max_tokens=800)
    need("<think>" not in r.text and "</think>" not in r.text, "think tag leaked")
    need("391" in r.text, "wrong/missing answer %r" % one_line(r, 60))
    return "%s  answer=%r  reasoning=%s" % (r.source, one_line(r, 20), "yes" if r.reasoning else "no")


@check("api", "model name resolution (alias / fuzzy / provider/model / unknown)")
def _resolve(ctx):
    c = ctx.client()
    need(c.models.resolve("fast"), "fast")
    need(c.models.resolve("llama"), "fuzzy llama")
    need(c.models.resolve("ovh/qwen3.5-9b")[0].startswith("ovh/"), "provider/model")
    try:
        c.models.resolve("definitely-not-a-model-xyz")
    except ModelNotFound:
        pass
    else:
        raise AssertionError("unknown model should raise ModelNotFound")
    return "ok"


@check("api", "models.list(live=True) discovers live ids", kind="provider", slow=True)
def _live(ctx):
    c = ctx.client()
    known = {m.name for m in c.models.list()}
    live = c.models.list(live=True)
    new = [m.name for m in live if m.name not in known]
    ctx.extra["live_new_models"] = new[:60]
    return "%d catalogued, %d extra live ids (e.g. %s)" % (len(known), len(new), ", ".join(new[:3]) or "-")


# =================================================================== stream
@check("stream", "stream() yields chunks and a final Reply")
def _stream(ctx):
    st = ctx.client().stream("Count from 1 to 5, separated by commas.")
    pieces = list(st)
    need(pieces and "".join(pieces).strip(), "no text")
    need(st.reply is not None and st.reply.text, "no final reply")
    return "%d chunks from %s: %r" % (len(pieces), st.reply.source, one_line("".join(pieces), 40))


@check("stream", "chat.completions.create(stream=True) chunk objects")
def _stream_sdk(ctx):
    chunks = list(ctx.client().chat.completions.create(
        messages=[{"role": "user", "content": "Say hi in 3 words."}], stream=True))
    need(chunks[0].choices[0].delta.role == "assistant", "first chunk role")
    need(chunks[-1].choices[0].finish_reason == "stop", "last chunk finish_reason")
    need("".join(c.text for c in chunks).strip(), "no text")
    return "%d chunks" % len(chunks)


def _provider_stream(name, model):
    @check("stream", "stream via %s (%s)" % (name, model), kind="provider", slow=True)
    def _fn(ctx):
        if name in LIMITED and not ctx.args.include_chatai:
            raise Skip("quota-limited")
        st = ctx.client().stream("Count from 1 to 8, separated by commas.", provider=name, model=model,
                                 fallback=False, max_tokens=400)
        t0 = time.time()
        first, pieces = None, []
        for p in st:
            if first is None:
                first = time.time() - t0
            pieces.append(p)
        need("".join(pieces).strip(), "empty stream")
        if len(pieces) == 1:
            raise Warn("works but delivered ONE chunk (no real streaming): %r" % one_line(pieces[0], 40))
        return "%d chunks, first after %.2fs" % (len(pieces), first or 0)


for _n, _m in PROVIDERS:
    _provider_stream(_n, _m)


# =================================================================== vision
@check("vision", "vision alias: describes a red image", slow=True)
def _vision(ctx):
    r = ctx.client().chat("What is the dominant color of this image? Answer with one word.",
                          images=[make_png()], max_tokens=400)
    if "red" not in r.text.lower():
        raise Warn("%s answered %r (expected 'red')" % (r.source, one_line(r, 40)))
    return "%s  %r" % (r.source, one_line(r, 30))


def _provider_vision():
    for name, _ in PROVIDERS:
        spec = next((p for p in _PROBE.providers.list() if p.name == name), None)
        vm = [m for m in _PROBE.models.list() if m.provider == name and m.vision and m.verified is not None]
        if not vm:
            continue
        model = vm[0].id

        def make(name=name, model=model):
            @check("vision", "vision via %s (%s)" % (name, model), kind="provider", slow=True)
            def _fn(ctx):
                if name in LIMITED and not ctx.args.include_chatai:
                    raise Skip("quota-limited")
                r = ctx.client().chat("What is the dominant color of this image? One word.", images=[make_png()],
                                      provider=name, model=model, fallback=False, max_tokens=400)
                if "red" not in r.text.lower():
                    raise Warn("answered %r (expected 'red')" % one_line(r, 40))
                return one_line(r, 40)
        make()


_provider_vision()


# ================================================================ resilience
@check("resilience", "dead provider in front -> falls back and still answers")
def _fallback(ctx):
    c = ctx.client(retries=0)
    c.register("dead", "http://127.0.0.1:9/v1", "x", front=True)
    r = c.chat("Say OK.", max_tokens=300)
    need(r.text, "empty")
    need(not r.attempts[0].ok and r.attempts[0].provider == "dead", "dead provider was not tried first")
    return "answered by %s after %d failed attempt(s)" % (r.source, sum(1 for a in r.attempts if not a.ok))


@check("resilience", "everything dead -> AllProvidersFailed quickly")
def _alldead(ctx):
    c = LLMF(builtin=False, use_cache=False, deadline=10, retries=1)
    c.register("dead1", "http://127.0.0.1:9/v1", "x")
    c.register("dead2", "http://127.0.0.1:1/v1", "y")
    t0 = time.time()
    try:
        c.chat("hi")
    except AllProvidersFailed as e:
        need(len(e.errors) >= 2, "errors not collected")
        return "raised after %.1fs with %d errors" % (time.time() - t0, len(e.errors))
    raise AssertionError("did not raise")


@check("resilience", "unknown explicit model with fallback=False raises, not silently swaps")
def _strict(ctx):
    c = ctx.client(retries=0)
    try:
        c.chat("hi", provider="ovh", model="this-model-does-not-exist-123", fallback=False)
    except AllProvidersFailed:
        return "raised as expected"
    raise AssertionError("should have raised")


@check("resilience", "race=2 answers (first success wins)")
def _race(ctx):
    r = ctx.client().chat("Say OK.", race=2, max_tokens=300)
    need(r.text, "empty")
    return "%s in %.2fs" % (r.source, r.latency)


@check("resilience", "routing='adaptive' answers and learns latencies")
def _adaptive(ctx):
    c = ctx.client(routing="adaptive")
    names = [r.source for r in (c.chat("Say OK.", max_tokens=300) for _ in range(3))]
    need(all(names), "empty")
    return " -> ".join(names)


@check("resilience", "min_interval throttling (Pollinations, 1 req/15 s)", kind="provider", slow=True)
def _poll(ctx):
    c = ctx.client(retries=0)
    t0 = time.time()
    for _ in range(2):
        c.chat("Say OK.", provider="pollinations", fallback=False, max_tokens=300)
    dt = time.time() - t0
    need(dt >= 14, "two calls took only %.1fs (throttle not applied?)" % dt)
    return "2 calls took %.1fs" % dt


# ===================================================================== proxy
@check("proxy", "proxy actually used (public IP differs from direct)")
def _proxy_ip(ctx):
    if not ctx.proxy:
        raise Skip("pass --proxy URL to test")
    from llmf import _http

    def ip(proxy):
        resp = _http.open_url("https://api.ipify.org", headers={"User-Agent": "llmf-live-test"},
                              timeout=ctx.args.timeout, proxy=proxy)
        try:
            return _http.decode_body(resp).strip()
        finally:
            resp.close()
    direct, via = ip(None), ip(ctx.proxy)
    scheme = ctx.proxy.split("://")[0]
    ctx.extra["proxy_scheme"] = scheme
    if direct == via:
        raise Warn("same IP direct and via proxy (%s) - proxy not changing your address?" % via)
    return "direct %s, via %s proxy %s" % (direct, scheme, via)


@check("proxy", "chat works through the proxy")
def _proxy_chat(ctx):
    if not ctx.proxy:
        raise Skip("pass --proxy URL to test")
    r = ctx.client().chat("Say OK.", max_tokens=300)
    need(r.text, "empty")
    return "%s in %.2fs" % (r.source, r.latency)


@check("proxy", "dead proxy -> clean AllProvidersFailed")
def _proxy_dead(ctx):
    for url in ("http://127.0.0.1:9", "socks5://127.0.0.1:9"):
        c = LLMF(use_cache=False, deadline=10, retries=0, proxy=url, max_attempts=2)
        try:
            c.chat("hi")
        except AllProvidersFailed:
            continue
        raise AssertionError("%s should fail" % url)
    return "http and socks5 dead proxies fail cleanly"


@check("proxy", "'auto' proxy is refused")
def _proxy_auto(ctx):
    try:
        LLMF(proxy="auto")
    except ValueError:
        return "refused"
    raise AssertionError("proxy='auto' should raise")


# ===================================================================== async
@check("async", "achat / astream")
def _async(ctx):
    import asyncio

    async def go():
        c = ctx.client()
        r = await c.achat("Say OK.", max_tokens=300)
        parts = [p async for p in c.astream("Count 1 to 3.", max_tokens=300)]
        return r, parts
    r, parts = asyncio.run(go())
    need(r.text and "".join(parts).strip(), "empty")
    return "achat %s, astream %d chunks" % (r.source, len(parts))


# ==================================================================== server
def _call(url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=90) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class _Server:
    def __init__(self, ctx, **kw):
        from llmf.server import make_server
        self.srv = make_server(ctx.client(), "127.0.0.1", 0, **kw)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@check("server", "llmf serve: /health, /v1/models, chat, stream")
def _server(ctx):
    s = _Server(ctx)
    try:
        st, body = _call(s.base + "/health")
        need(st == 200 and json.loads(body)["status"] == "ok", "health")
        st, body = _call(s.base + "/v1/models")
        ids = [m["id"] for m in json.loads(body)["data"]]
        need(st == 200 and "fast" in ids, "models")
        st, body = _call(s.base + "/v1/chat/completions", {
            "model": "gpt-4o", "messages": [{"role": "user", "content": "Say OK."}], "max_tokens": 300})
        j = json.loads(body)
        need(st == 200 and j["choices"][0]["message"]["content"], "chat: %s" % body[:120])
        st, body = _call(s.base + "/v1/chat/completions", {
            "model": "fast", "stream": True, "max_tokens": 300,
            "messages": [{"role": "user", "content": "Count 1 to 4."}]})
        events = [e[6:] for e in body.split("\n\n") if e.startswith("data: ")]
        need(st == 200 and events and events[-1] == "[DONE]", "SSE did not end with [DONE]")
        text = "".join(json.loads(e)["choices"][0]["delta"].get("content", "") for e in events[:-1])
        need(text.strip(), "empty stream")
        return "ok; answered by %s; stream %d events" % (j["model"], len(events))
    finally:
        s.close()


@check("server", "llmf serve: api key + error shapes")
def _server_auth(ctx):
    s = _Server(ctx, api_key="k123", strict_models=True)
    try:
        body = {"messages": [{"role": "user", "content": "hi"}]}
        need(_call(s.base + "/v1/chat/completions", body)[0] == 401, "no key should be 401")
        st, b = _call(s.base + "/v1/chat/completions", dict(body, model="nope-xyz"),
                      {"Authorization": "Bearer k123"})
        need(st == 404 and json.loads(b)["error"]["code"] == "model_not_found", "strict model 404: %s" % b[:80])
        need(_call(s.base + "/v1/chat/completions", {"messages": []}, {"Authorization": "Bearer k123"})[0] == 400,
             "empty messages should be 400")
        return "401 / 404 / 400 as expected"
    finally:
        s.close()


@check("server", "official `openai` SDK works against llmf serve")
def _openai_sdk(ctx):
    try:
        from openai import OpenAI
    except ImportError:
        raise Skip("pip install openai to test")
    s = _Server(ctx)
    try:
        c = OpenAI(base_url=s.base + "/v1", api_key="x", timeout=90)
        r = c.chat.completions.create(model="fast", messages=[{"role": "user", "content": "Say OK."}],
                                      max_tokens=300)
        need(r.choices[0].message.content, "empty")
        got = "".join((ch.choices[0].delta.content or "") for ch in c.chat.completions.create(
            model="fast", messages=[{"role": "user", "content": "Count 1 to 3."}], max_tokens=300, stream=True)
            if ch.choices)
        need(got.strip(), "empty stream")
        return "sync + stream ok via openai %s" % __import__("openai").__version__
    finally:
        s.close()


# ======================================================================= cli
def _cli(ctx, *argv, stdin=None, timeout=240):
    env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
               LLMF_NO_CACHE="1")
    cmd = [sys.executable, "-m", "llmf"] + list(argv)
    if ctx.proxy:
        cmd += ["--proxy", ctx.proxy]
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, p.stdout, p.stderr


@check("cli", "llmf \"question\"")
def _cli_ask(ctx):
    code, out, err = _cli(ctx, "-v", "Say OK.", "--max-tokens", "300")
    need(code == 0 and out.strip(), "exit %s: %s" % (code, err[-200:]))
    return one_line(out, 40) + "  " + one_line(err, 50)


@check("cli", "stdin pipe + -m fast + --json")
def _cli_pipe(ctx):
    code, out, err = _cli(ctx, "Translate to English:", "-m", "fast", "--json", "--max-tokens", "300",
                          stdin="Xin chào thế giới")
    need(code == 0, err[-200:])
    j = json.loads(out)
    need(j["text"] and j["provider"], "json shape")
    return "%s: %r" % (j["provider"], one_line(j["text"], 40))


@check("cli", "llmf models / providers / models resolve")
def _cli_lists(ctx):
    for argv in (["models"], ["providers"], ["models", "resolve", "fast"], ["version"]):
        code, out, err = _cli(ctx, *argv)
        need(code == 0 and out.strip(), "%s -> %s %s" % (argv, code, err[-100:]))
    return "4 commands ok"


@check("cli", "llmf doctor -p ovh --no-save", kind="provider")
def _cli_doctor(ctx):
    code, out, err = _cli(ctx, "doctor", "-p", "ovh", "--no-save")
    need("OK" in out or "FAIL" in out, "no table: %s" % err[-150:])
    return out.count("OK ") and "%d ok lines" % out.count("OK ")


@check("cli", "llmf serve (real process) answers HTTP", slow=True)
def _cli_serve(ctx):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
               LLMF_NO_CACHE="1")
    cmd = [sys.executable, "-m", "llmf", "serve", "--port", str(port)]
    if ctx.proxy:
        cmd += ["--proxy", ctx.proxy]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        for _ in range(50):
            try:
                st, _b = _call("http://127.0.0.1:%d/health" % port)
                if st == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("server did not start")
        st, body = _call("http://127.0.0.1:%d/v1/chat/completions" % port,
                         {"model": "fast", "messages": [{"role": "user", "content": "Say OK."}], "max_tokens": 300})
        need(st == 200, body[:120])
        return "port %d: %r" % (port, one_line(json.loads(body)["choices"][0]["message"]["content"], 40))
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


# ===================================================================== cache
@check("cache", "doctor cache is written and re-read by a new client")
def _cache(ctx):
    with tempfile.TemporaryDirectory() as d:
        c = LLMF(cache_dir=d, timeout=ctx.args.timeout, proxy=ctx.proxy)
        res = c.models.check(providers=["ovh"])
        need(any(r.ok for r in res), "ovh answered nothing, cannot test cache")
        need(os.path.exists(os.path.join(d, "health.json")), "health.json not written")
        c2 = LLMF(cache_dir=d, timeout=ctx.args.timeout)
        from llmf.registry import Target
        ok = next(r for r in res if r.ok)
        need(c2._state.latency(Target(ok.provider, ok.model)) is not None, "latency not seeded")
        return "saved %d results, reloaded latency for %s" % (len(res), ok.name)


# ==================================================================== extras
@check("extras", "chatai (quota ~3-5/IP/day)", kind="provider")
def _chatai(ctx):
    if not ctx.args.include_chatai:
        raise Skip("use --include-chatai (burns daily quota)")
    r = ctx.client().chat("Say OK.", provider="chatai", fallback=False)
    need(r.text, "empty")
    return "%s: %r" % (r.source, one_line(r, 40))


@check("extras", "tools.ask_langchain_docs()", kind="provider")
def _langchain(ctx):
    if not ctx.args.include_langchain:
        raise Skip("use --include-langchain")
    r = llmf.tools.ask_langchain_docs("How do I create an agent in LangChain?", timeout=ctx.args.timeout, proxy=ctx.proxy)
    need(r.text, "empty")
    return "off_topic=%s  %r" % (r.off_topic, one_line(r, 50))


@check("extras", "discover() (stillworks)", kind="provider")
def _discover(ctx):
    if not ctx.args.include_discover:
        raise Skip("use --include-discover")
    names = ctx.client().discover(limit=3)
    need(names, "no endpoints returned")
    return "registered %s" % names


# ===================================================================== runner
def main():
    ap = argparse.ArgumentParser(description="llmf live test", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--quick", action="store_true", help="skip slow checks (per-provider streaming/vision, long prompt...)")
    ap.add_argument("--only", help="comma list of groups: " + ",".join(GROUPS))
    ap.add_argument("--proxy", help="run everything through this proxy (http/https/socks*)")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--all-models", action="store_true", help="doctor also tests live-listed models")
    ap.add_argument("--include-chatai", action="store_true")
    ap.add_argument("--include-langchain", action="store_true")
    ap.add_argument("--include-discover", action="store_true")
    ap.add_argument("--report", default="llmf_live_report.json")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    color = sys.stdout.isatty() and not args.no_color
    only = set(args.only.split(",")) if args.only else None
    ctx = Ctx(args)
    results = []
    t_start = time.time()
    print("llmf %s live test  (python %s, proxy=%s)\n" % (llmf.__version__, sys.version.split()[0],
                                                          ctx.proxy.split("://")[0] + "://***" if ctx.proxy else "none"))
    cur = None
    for group, name, kind, slow, fn in CHECKS:
        if only and group not in only:
            continue
        if group != cur:
            cur = group
            print("== %s ==" % group)
        t0 = time.time()
        detail = ""
        if args.quick and slow:
            status, detail = SKIP, "--quick"
        else:
            try:
                detail = fn(ctx) or ""
                status = PASS
            except Skip as e:
                status, detail = SKIP, str(e)
            except Warn as e:
                status, detail = WARN, str(e)
            except AssertionError as e:
                status, detail = FAIL, str(e) or "assertion failed"
            except Exception as e:  # noqa: BLE001 - report any crash instead of dying
                status = FAIL
                detail = "%s: %s" % (type(e).__name__, one_line(e, 150))
                if os.environ.get("LLMF_LIVE_DEBUG"):
                    traceback.print_exc()
        dt = time.time() - t0
        c = COLORS[status] if color else ""
        z = "\033[0m" if color else ""
        print("  %s%-4s%s %-62s %6.1fs  %s" % (c, status, z, name[:62], dt, one_line(detail, 100)), flush=True)
        results.append({"group": group, "name": name, "kind": kind, "status": status,
                        "seconds": round(dt, 2), "detail": one_line(detail, 300)})
    total = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, WARN, FAIL, SKIP)}
    core_fail = [r for r in results if r["status"] == FAIL and r["kind"] == "core"]
    prov_fail = [r for r in results if r["status"] == FAIL and r["kind"] == "provider"]
    print("\n== summary (%.0fs) ==" % (time.time() - t_start))
    print("  PASS %d   WARN %d   FAIL %d (core %d, provider %d)   SKIP %d" % (
        total[PASS], total[WARN], total[FAIL], len(core_fail), len(prov_fail), total[SKIP]))
    for r in core_fail:
        print("  CORE FAIL: %s -> %s" % (r["name"], r["detail"]))
    report = {"llmf": llmf.__version__, "python": sys.version.split()[0], "platform": platform.platform(),
              "proxy_scheme": ctx.proxy.split("://")[0] if ctx.proxy else None, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
              "args": {k: v for k, v in vars(args).items() if k != "proxy"}, "totals": total,
              "results": results, "extra": ctx.extra}
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("  report written to %s" % os.path.abspath(args.report))
    return 1 if core_fail else 0


if __name__ == "__main__":
    sys.exit(main())
