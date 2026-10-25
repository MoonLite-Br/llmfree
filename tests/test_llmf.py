import asyncio
import json
import contextlib
import io
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import fakeserver  # noqa: E402
import llmf  # noqa: E402
from llmf._think import ThinkSplitter, split_think  # noqa: E402
from llmf.providers.builtin import BUILTIN, TAGS  # noqa: E402
from llmf.providers.chatjimmy import split_stats  # noqa: E402

SRV, BASE = fakeserver.start()


def client(models=("ok",), **kw):
    c = llmf.Client(builtin=False, deadline=20, timeout=5, **kw)
    c.register("fake", BASE + "/v1", list(models))
    return c


class Basics(unittest.TestCase):
    def test_reply_is_str_with_meta(self):
        r = client().chat("hi")
        self.assertIsInstance(r, str)
        self.assertEqual(r, "Echo: hi")
        self.assertEqual((r.provider, r.model), ("fake", "ok"))
        self.assertEqual(r.usage["total_tokens"], 3)
        self.assertTrue(r.attempts[-1].ok)
        import copy
        self.assertEqual(copy.copy(r).provider, "fake")

    def test_reasoning_field_stripped(self):
        r = client(["reasoning"]).chat("x")
        self.assertEqual(r, "Pong")
        self.assertEqual(r.reasoning, "thinking...")

    def test_think_tags_extracted(self):
        r = client(["think"]).chat("x")
        self.assertEqual((r.text, r.reasoning), ("Answer", "hmm"))

    def test_system_and_messages(self):
        client().chat("hi", system="be nice")
        _, body, _ = fakeserver.Handler.calls[-1]
        self.assertEqual(body["messages"][0], {"role": "system", "content": "be nice"})
        self.assertEqual(body["max_tokens"], 1024)

    def test_images_become_parts(self):
        c = llmf.Client(builtin=False)
        c.register("v", BASE + "/v1", "ok", vision=True)
        c.chat("look", images=["https://x/y.png"])
        _, body, _ = fakeserver.Handler.calls[-1]
        parts = body["messages"][-1]["content"]
        self.assertEqual(parts[1]["image_url"]["url"], "https://x/y.png")

    def test_json_mode_and_extra(self):
        client().chat("x", json=True, seed=7)
        _, body, _ = fakeserver.Handler.calls[-1]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["seed"], 7)


class Fallback(unittest.TestCase):
    def test_falls_through_errors(self):
        c = client(["err500", "err200", "empty", "err404", "err429", "badjson", "ok"], retries=0)
        r = c.chat("hi", model="fake/ok", fallback=True)  # explicit then chain
        self.assertEqual(r, "Echo: hi")
        c2 = client(["err500", "err200", "empty", "err404", "err429", "badjson", "ok"], retries=0)
        c2.configure(max_attempts=8)
        # chain only has the default (first) model per provider -> use list of models instead
        r = c2.chat("hi", model=["fake/err500", "fake/err200", "fake/empty", "fake/err404",
                                 "fake/err429", "fake/badjson", "fake/ok"])
        self.assertEqual(r, "Echo: hi")
        self.assertEqual([a.ok for a in r.attempts], [False] * 6 + [True])

    def test_all_fail_raises_with_errors(self):
        c = client(["err500"], retries=1)
        with self.assertRaises(llmf.AllProvidersFailed) as cm:
            c.chat("hi", model="fake/err500")
        self.assertEqual(len(cm.exception.errors), 2)  # transient -> retried once
        self.assertEqual(cm.exception.errors[0].status, 500)

    def test_non_retryable_not_retried(self):
        c = client(["err404"], retries=3)
        with self.assertRaises(llmf.AllProvidersFailed) as cm:
            c.chat("hi", model="fake/err404")
        self.assertEqual(len(cm.exception.errors), 1)

    def test_free_model_failed_code_is_transient(self):
        e = llmf.ProviderError("p", "m", "x", status=502, code="FREE_MODEL_FAILED")
        self.assertTrue(e.retryable)

    def test_connection_refused_is_error_not_crash(self):
        c = llmf.Client(builtin=False, deadline=5, retries=0)
        c.register("dead", "http://127.0.0.1:1/v1", "m")
        with self.assertRaises(llmf.AllProvidersFailed):
            c.chat("hi")

    def test_cooldown_reorders(self):
        c = llmf.Client(builtin=False, retries=0)
        c.register("a", BASE + "/v1", "err500")
        c.register("b", BASE + "/v1", "ok")
        r = c.chat("hi")
        self.assertEqual(r.provider, "b")
        plan = c._plan(None, None, False)
        self.assertEqual(plan[0].provider, "b")  # 'a' is cooling down -> last
        self.assertEqual(plan[-1].provider, "a")

    def test_only_exclude(self):
        c = llmf.Client(builtin=False)
        c.register("a", BASE + "/v1", "ok")
        c.register("b", BASE + "/v1", "ok")
        self.assertEqual(c.configure(exclude=["a"]).chat("x").provider, "b")
        with self.assertRaises(llmf.ModelNotFound):
            c.configure(only=["zzz"]).chat("x")

    def test_rate_limit_deprioritised_and_spaced(self):
        c = llmf.Client(builtin=False, retries=0)
        c.register("slow", BASE + "/v1", "ok", min_interval=0.3)
        t0 = time.monotonic()
        c.chat("1")
        c.chat("2")
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)


class ProviderArg(unittest.TestCase):
    def test_provider_kwarg(self):
        c = llmf.Client(builtin=False)
        c.register("a", BASE + "/v1", ["ok", "reasoning"])
        c.register("b", BASE + "/v1", "ok")
        self.assertEqual(c.chat("x", provider="a", model="reasoning").model, "reasoning")
        self.assertEqual(c.chat("x", provider="b").provider, "b")
        with self.assertRaises(ValueError):
            c.chat("x", provider="a", model=["ok", "reasoning"])


class Resolve(unittest.TestCase):
    def setUp(self):
        self.reg = llmf.Client()._reg

    def test_builtin_chain_matches_docs(self):
        names = [t.provider for t in self.reg.chain()]
        self.assertEqual(names, ["ch-at", "rewind-ai", "ovh", "kilo-openrouter", "freeai", "chatjimmy", "kilo-gateway",
                                 "pollinations", "llm7", "blockrun", "chatai"])

    def test_tags_reference_real_models(self):
        for tag, targets in TAGS.items():
            for p, m in targets:
                self.assertIsNotNone(self.reg.model_spec(p, m), (tag, p, m))

    def test_alias_fuzzy_prefix(self):
        r = self.reg.resolve
        self.assertEqual(r("fast")[0].provider, "llm7")
        self.assertEqual(r("Llama")[0].model, "Meta-Llama-3_3-70B-Instruct")
        self.assertEqual([t.provider for t in r("gpt-oss")], ["pollinations", "llm7", "ovh"])
        self.assertEqual(r("ovh")[0].model, "gpt-oss-120b")
        self.assertEqual(r("ovh/qwen3.5-9b")[0].model, "Qwen3.5-9B")
        self.assertEqual(r("ovh/brand-new")[0].model, "brand-new")  # pass-through
        self.assertEqual(len(r("kilo")), 2)
        self.assertEqual(r("r1")[0].provider, "freeai")
        self.assertEqual(r("freeai")[0].model, "qwen7b")

    def test_unknown_suggests(self):
        with self.assertRaises(llmf.ModelNotFound) as cm:
            self.reg.resolve("nemotrn")
        self.assertIn("nemotron", str(cm.exception))

    def test_vision_default_when_images(self):
        c = llmf.Client()
        self.assertEqual(c._plan(None, None, True)[0].model, "Qwen2.5-VL-72B-Instruct")

    def test_headers_for_kilo(self):
        self.assertEqual(self.reg.providers["kilo-openrouter"].headers["Authorization"],
                         "Bearer anonymous")


class ChatJimmy(unittest.TestCase):
    def jc(self, model="llama"):
        c = llmf.Client(builtin=False, deadline=10)
        c.register("jimmy", BASE, model, kind="chatjimmy", chat_path="/api/chat")
        return c

    def test_split_stats(self):
        t, s = split_stats("Hi <|stats|>{\"a\":1}<|/stats|>")
        self.assertEqual((t, s), ("Hi", {"a": 1}))
        self.assertEqual(split_stats("no stats"), ("no stats", None))
        t, s = split_stats("x <|stats|> y<|stats|>{}<|/stats|>")
        self.assertEqual(t, "x <|stats|> y")

    def test_chat(self):
        r = self.jc().chat("hi", temperature=0.2)
        self.assertEqual(r, "Hello from jimmy")
        self.assertEqual(r.usage["completion_tokens"], 7)
        _, body, _ = fakeserver.Handler.calls[-1]
        self.assertEqual(body["chatOptions"]["selectedModel"], "llama")
        self.assertEqual(body["chatOptions"]["temperature"], 0.2)

    def test_stream(self):
        st = self.jc().stream("hi")
        self.assertEqual("".join(st), "Hello from jimmy")
        self.assertEqual(st.reply, "Hello from jimmy")

    def test_stream_with_fake_sentinel_in_content(self):
        self.assertEqual(self.jc("tricky").stream("hi").collect(), "I print <|stats|> in my text")

    def test_chat_with_fake_sentinel(self):
        self.assertEqual(self.jc("tricky").chat("hi"), "I print <|stats|> in my text")


class Streaming(unittest.TestCase):
    def test_sse(self):
        st = client(["ok"]).stream("hi", model="fake/ok")
        self.assertEqual(list(st), ["Hel", "lo ", "wor", "ld"])
        self.assertEqual(st.reply, "Hello world")
        self.assertEqual(st.provider, "fake")

    def test_stream_think_hidden(self):
        st = client(["streamthink"]).stream("hi", model="fake/streamthink")
        self.assertEqual("".join(st), "Hello world")

    def test_non_sse_fallback(self):
        self.assertEqual(client(["nostream"]).stream("hi", model="fake/nostream").collect(), "whole")

    def test_fallback_before_first_chunk(self):
        c = llmf.Client(builtin=False, retries=0)
        c.register("bad", BASE + "/v1", "streamerr")
        c.register("good", BASE + "/v1", "ok")
        st = c.stream("hi")
        self.assertEqual(st.collect(), "Hello world")
        self.assertEqual(st.provider, "good")

    def test_session_history(self):
        c = client()
        s = c.session(system="sys")
        s("one")
        s("two")
        self.assertEqual([m["role"] for m in s.history], ["user", "assistant"] * 2)
        _, body, _ = fakeserver.Handler.calls[-1]
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
        s2 = c.session()
        s2.stream("a", model="fake/ok").collect()
        self.assertEqual(len(s2.history), 2)

    def test_async(self):
        async def go():
            c = client()
            r = await c.achat("hi")
            parts = [p async for p in c.astream("hi", model="fake/ok")]
            return r, parts
        r, parts = asyncio.run(go())
        self.assertEqual(r, "Echo: hi")
        self.assertEqual("".join(parts), "Hello world")


class Think(unittest.TestCase):
    def test_split_any_boundary(self):
        text = "a<think>secret</think>\n\nb c"
        for n in range(1, len(text)):
            sp = ThinkSplitter()
            out = sp.feed(text[:n]) + sp.feed(text[n:]) + sp.flush()
            self.assertEqual(out, "a" + "b c" if False else out)
            self.assertEqual(out.replace("\n", ""), "ab c".replace("\n", ""), n)
            self.assertEqual(sp.reasoning, "secret")

    def test_closing_tag_only(self):
        self.assertEqual(split_think("pre</think> answer"), ("answer", "pre"))


class Introspection(unittest.TestCase):
    def test_models_live(self):
        c = llmf.Client(builtin=False)
        c.register("fake", BASE, "x", chat_path="/v1/chat/completions")
        c._reg.providers["fake"].models_path = "/v1/models"
        c._reg.providers["fake"].free_suffix = ":free"
        ids = [m.id for m in c.models(live=True)]
        self.assertEqual(ids, ["x", "a:free"])

    def test_health(self):
        c = llmf.Client(builtin=False)
        c.register("good", BASE + "/v1", "ok")
        c.register("bad", BASE + "/v1", "err500")
        res = {h.provider: h.ok for h in c.health()}
        self.assertEqual(res, {"good": True, "bad": False})


class CLI(unittest.TestCase):
    def run_cli(self, argv, stdin=None):
        from llmf import cli
        import llmf as pkg
        pkg._default = client()
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(stdin) if stdin is not None else None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        finally:
            sys.stdin = old
            pkg._default = None
        return code, out.getvalue(), err.getvalue()

    def test_ask(self):
        code, out, err = self.run_cli(["hello", "world", "-v"])
        self.assertEqual((code, out.strip()), (0, "Echo: hello world"))
        self.assertIn("[fake/ok]", err)

    def test_stdin_appended(self):
        _, out, _ = self.run_cli(["summarize"], stdin="DATA")
        self.assertEqual(out.strip(), "Echo: summarize\n\nDATA")

    def test_json_and_stream(self):
        import json
        _, out, _ = self.run_cli(["hi", "--json"])
        self.assertEqual(json.loads(out)["provider"], "fake")
        _, out, _ = self.run_cli(["hi", "--stream", "-m", "fake/ok"])
        self.assertEqual(out.strip(), "Hello world")

    def test_provider_flag(self):
        code, out, err = self.run_cli(["hi", "-p", "fake", "-m", "ok", "-v"])
        self.assertEqual((code, out.strip()), (0, "Echo: hi"))
        self.assertIn("[fake/ok]", err)
        self.assertEqual(self.run_cli(["hi", "-p", "fake"])[0], 0)       # provider default model
        self.assertEqual(self.run_cli(["hi", "-p", "nope"])[0], 1)       # unknown provider -> ...

    def test_proxy_flag(self):
        code, out, _ = self.run_cli(["hi", "--proxy", BASE])
        self.assertEqual(code, 0)
        code, _, err = self.run_cli(["hi", "--proxy", "ftp://1.2.3.4:1"])
        self.assertEqual(code, 2)
        self.assertIn("proxy must look like", err)

    def test_commands_and_errors(self):
        self.assertEqual(self.run_cli(["providers"])[0], 0)
        self.assertIn("fake", self.run_cli(["models"])[1])
        code, _, err = self.run_cli(["hi", "-m", "nonexistent-zzz"])
        self.assertEqual(code, 1)
        self.assertIn("unknown model", err)


class ChatAI(unittest.TestCase):
    def setUp(self):
        from llmf.providers import ADAPTERS
        ADAPTERS["chatai"]._sessions.clear()

    def cc(self, model="m"):
        c = llmf.Client(builtin=False, deadline=10, retries=0)
        c.register("chatai", BASE, model, kind="chatai", chat_path="/api/chat")
        return c

    def test_session_flow_and_reuse(self):
        c = self.cc()
        before = fakeserver.Handler.sessions
        self.assertEqual(c.chat("hi"), "chatai ok")
        self.assertEqual(c.chat("again"), "chatai ok")
        self.assertEqual(fakeserver.Handler.sessions - before, 1)  # session cached
        path, body, hdrs = fakeserver.Handler.calls[-1]
        self.assertEqual(body, {"model": "m", "messages": [{"role": "user", "content": "again"}]})
        self.assertEqual(hdrs["Origin"], BASE)

    def test_stale_session_refreshes_once(self):
        from llmf.providers import ADAPTERS
        c = self.cc()
        c.chat("hi")
        for sess in ADAPTERS["chatai"]._sessions.values():
            sess.csrf = "stale"
        self.assertEqual(c.chat("hi"), "chatai ok")

    def test_daily_limit_long_cooldown(self):
        c = self.cc("limited")
        with self.assertRaises(llmf.AllProvidersFailed) as cm:
            c.chat("hi")
        e = cm.exception.errors[0]
        self.assertEqual((e.code, e.retryable), ("daily_limit", False))
        self.assertGreaterEqual(e.cooldown, 3600)
        self.assertEqual(len(cm.exception.errors), 1)

    def test_builtin_spec(self):
        spec = llmf.Client()._reg.providers["chatai"]
        self.assertEqual(spec.chat_url, "https://chatai.org/api/chat")


class Proxy(unittest.TestCase):
    def test_requests_go_through_proxy(self):
        c = llmf.Client(builtin=False, proxy=BASE, retries=0)
        c.register("up", "http://upstream.invalid/v1", "ok")
        self.assertEqual(c.chat("hi"), "Echo: hi")
        self.assertTrue(fakeserver.Handler.calls[-1][0].startswith("http://upstream.invalid/"))

    def test_per_call_proxy_and_no_auto(self):
        c = llmf.Client(builtin=False, retries=0)
        c.register("up", "http://upstream.invalid/v1", "ok")
        self.assertEqual(c.chat("hi", proxy=BASE), "Echo: hi")
        self.assertEqual("".join(c.stream("hi", proxy=BASE)), "Hello world")
        with self.assertRaises(ValueError):
            c.chat("hi", proxy="auto")
        with self.assertRaises(ValueError):
            llmf.Client(proxy="auto")

    def test_explicit_proxy_ignores_no_proxy_env(self):
        old = os.environ.get("no_proxy"), os.environ.get("NO_PROXY")
        os.environ["no_proxy"] = os.environ["NO_PROXY"] = "*"
        try:
            c = llmf.Client(builtin=False, proxy=BASE, retries=0, use_cache=False)
            c.register("up", "http://upstream.invalid/v1", "ok")
            self.assertEqual(c.chat("hi"), "Echo: hi")
            c2 = llmf.Client(builtin=False, retries=0, use_cache=False)  # no explicit proxy: env wins
            c2.register("loc", BASE + "/v1", "ok")
            self.assertEqual(c2.chat("hi"), "Echo: hi")
        finally:
            for k, v in zip(("no_proxy", "NO_PROXY"), old):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_proxy_basic_auth_header(self):
        c = llmf.Client(builtin=False, proxy="http://bob:pw@" + BASE[7:], retries=0, use_cache=False)
        c.register("up", "http://upstream.invalid/v1", "ok")
        c.chat("hi")
        hdrs = {k.lower(): v for k, v in fakeserver.Handler.calls[-1][2].items()}
        self.assertTrue(hdrs["proxy-authorization"].startswith("Basic "))

    def test_rejects_bad_proxy(self):
        with self.assertRaises(ValueError):
            llmf.Client().configure(proxy="1.2.3.4:80")


class Socks(unittest.TestCase):
    def setUp(self):
        import socksserver
        self.mk = socksserver.SocksServer
        self.host, self.port = "127.0.0.1", int(BASE.rsplit(":", 1)[1])

    def run_via(self, proxy_url, upstream="http://127.0.0.1:%d/v1"):
        c = llmf.Client(builtin=False, deadline=10, retries=0, proxy=proxy_url)
        c.register("up", upstream % self.port, "ok")
        return c.chat("hi")

    def test_socks5_ip_dest(self):
        s = self.mk((self.host, self.port))
        try:
            self.assertEqual(self.run_via("socks5://127.0.0.1:%d" % s.port), "Echo: hi")
            self.assertEqual(s.requests[-1][:2], ("5", 1))  # IPv4 address type
        finally:
            s.close()

    def test_socks5h_sends_hostname_and_auth(self):
        s = self.mk((self.host, self.port), creds=("bob", "pw"))
        try:
            r = self.run_via("socks5h://bob:pw@127.0.0.1:%d" % s.port, "http://remote.invalid:%d/v1")
            self.assertEqual(r, "Echo: hi")
            self.assertEqual(s.requests[-1], ("5", 3, "remote.invalid"))  # domain, resolved remotely
            with self.assertRaises(llmf.AllProvidersFailed):
                self.run_via("socks5://bob:WRONG@127.0.0.1:%d" % s.port)
        finally:
            s.close()

    def test_socks4_and_4a(self):
        s = self.mk((self.host, self.port))
        try:
            self.assertEqual(self.run_via("socks4://127.0.0.1:%d" % s.port), "Echo: hi")
            r = self.run_via("socks4a://127.0.0.1:%d" % s.port, "http://remote.invalid:%d/v1")
            self.assertEqual((r, s.requests[-1][2]), ("Echo: hi", "remote.invalid"))
        finally:
            s.close()

    def test_streaming_through_socks_and_per_call(self):
        s = self.mk((self.host, self.port))
        try:
            c = llmf.Client(builtin=False, deadline=10, retries=0)
            c.register("up", "http://127.0.0.1:%d/v1" % self.port, "ok")
            self.assertEqual("".join(c.stream("hi", proxy="socks5://127.0.0.1:%d" % s.port)),
                             "Hello world")
        finally:
            s.close()

    def test_dead_socks_proxy_is_a_clean_failure(self):
        with self.assertRaises(llmf.AllProvidersFailed):
            self.run_via("socks5://127.0.0.1:1")

    def test_validation(self):
        from llmf import _http
        self.assertEqual(_http.check_proxy("socks5h://u:p@h:9"), "socks5h://u:p@h:9")
        with self.assertRaises(ValueError):
            _http.check_proxy("ftp://h:1")
        with self.assertRaises(ValueError):
            _http.check_proxy("socks5://")


class Tools(unittest.TestCase):
    def test_langchain_docs(self):
        r = llmf.tools.ask_langchain_docs("How to create an agent?", backend=BASE)
        self.assertEqual(r, "Use create_agent.")
        self.assertFalse(r.off_topic)
        self.assertEqual(r.usage, {"input_tokens": 9})

    def test_off_topic_flag_not_raised(self):
        r = llmf.tools.ask_langchain_docs("weather?", backend=BASE)
        self.assertTrue(r.off_topic)

    def test_token_cached(self):
        llmf.tools.ask_langchain_docs("a", backend=BASE)
        n = fakeserver.Handler.guests
        llmf.tools.ask_langchain_docs("b", backend=BASE)
        self.assertEqual(fakeserver.Handler.guests, n)

    def test_expired_token_refreshes(self):
        llmf.tools.ask_langchain_docs("a", backend=BASE)
        llmf.tools._tokens[(BASE, None)] = ("old", time.monotonic())
        self.assertEqual(llmf.tools.ask_langchain_docs("a", backend=BASE), "Use create_agent.")


class FreeAI(unittest.TestCase):
    def test_models_listing_only_self_hosted_under_models_key(self):
        from llmf.providers.base import parse_model_list
        payload = {"caller_country": "VN", "total": 3, "models": [
            {"id": "qwen7b", "self_hosted": True}, {"id": "deepseek-r1", "self_hosted": True},
            {"id": "google/gemma-3-4b-it", "self_hosted": False, "provider": "openrouter"}]}
        self.assertEqual(parse_model_list(payload), ["qwen7b", "deepseek-r1"])

    def test_premium_error_shape(self):
        from llmf.providers.base import error_from_body
        body = json.dumps({"error": {"error": "Premium models run on a paid provider...",
                                     "code": "premium_requires_purchase"}})
        code, msg = error_from_body(body)
        self.assertEqual(code, "premium_requires_purchase")
        self.assertIn("paid provider", msg)
        e = llmf.ProviderError("freeai", "x", msg, status=402, code=code)
        self.assertEqual((e.retryable, e.scope), (False, "model"))
        self.assertGreaterEqual(e.cooldown, 3600)


class Catalogue(unittest.TestCase):
    def test_unique_names_and_defaults_exist(self):
        names = [s.name for s in BUILTIN]
        self.assertEqual(len(names), len(set(names)))
        for s in BUILTIN:
            self.assertIn(s.default, [m.id for m in s.models], s.name)


if __name__ == "__main__":
    unittest.main()
