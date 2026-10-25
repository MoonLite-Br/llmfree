import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

os.environ["LLMF_NO_CACHE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import fakeserver  # noqa: E402
import llmf  # noqa: E402
from llmf import LLMF  # noqa: E402

SRV, BASE = fakeserver.start()


def llm(models=("ok",), **kw):
    c = LLMF(builtin=False, deadline=20, timeout=5, retries=0, use_cache=False, **kw)
    c.register("fake", BASE + "/v1", list(models))
    return c


class SDKSyntax(unittest.TestCase):
    def test_openai_shaped_completion(self):
        r = llm().chat.completions.create(
            model="fake/ok", messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
            max_tokens=77, temperature=0.2, response_format={"type": "json_object"}, seed=3)
        self.assertEqual(r.choices[0].message.content, "Echo: hi")
        self.assertEqual((r.output_text, str(r)), ("Echo: hi", "Echo: hi"))
        self.assertEqual((r.model, r.provider, r.object), ("fake/ok", "fake", "chat.completion"))
        self.assertEqual(r.usage.total_tokens, 3)
        d = r.to_dict()
        self.assertEqual(d["choices"][0]["message"], {"role": "assistant", "content": "Echo: hi"})
        up = fakeserver.Handler.calls[-1][1]
        self.assertEqual((up["max_tokens"], up["temperature"], up["seed"]), (77, 0.2, 3))
        self.assertEqual(up["response_format"], {"type": "json_object"})

    def test_stream_chunks(self):
        st = llm().chat.completions.create(model="fake/ok", stream=True,
                                           messages=[{"role": "user", "content": "x"}])
        chunks = list(st)
        self.assertEqual(chunks[0].choices[0].delta.role, "assistant")
        self.assertEqual("".join(c.text for c in chunks), "Hello world")
        self.assertEqual(chunks[-1].choices[0].finish_reason, "stop")
        self.assertEqual(chunks[1].model, "fake/ok")
        self.assertEqual(chunks[1].to_dict()["object"], "chat.completion.chunk")
        self.assertEqual(st.collect().output_text, "Hello world")

    def test_n_gt_1_rejected(self):
        with self.assertRaises(ValueError):
            llm().chat.completions.create(messages=[{"role": "user", "content": "x"}], n=2)

    def test_shorthand_and_namespaces_coexist(self):
        c = llm()
        self.assertEqual(c.chat("hi"), "Echo: hi")                      # callable
        self.assertEqual([m.name for m in c.models()], ["fake/ok"])     # callable
        self.assertEqual([m.name for m in c.models.list()], ["fake/ok"])
        self.assertEqual(c.providers.list()[0].name, "fake")
        self.assertEqual(c.models.resolve("fake/ok"), ["fake/ok"])

    def test_module_level_mirrors(self):
        llmf.default_client()  # create
        self.assertTrue(callable(llmf.chat))
        self.assertTrue(hasattr(llmf.chat, "completions"))
        self.assertEqual(llmf.models.resolve("fast")[0], "llm7/minimax-m2.7")
        self.assertEqual(llmf.LLMF, llmf.Client)


class Catalogue(unittest.TestCase):
    def test_broken_models_never_chosen_automatically(self):
        reg = llmf.Client(use_cache=False)._reg
        with self.assertRaises(llmf.ModelNotFound):
            reg.resolve("nemotron-3-super")             # only broken match -> not found
        self.assertNotIn("m3.1", " ".join(map(str, reg.tag("fast"))))
        self.assertNotIn("north-mini-code", " ".join(str(t) for t in reg.tag("code") if t.provider == "blockrun"))
        # still reachable explicitly
        self.assertEqual(reg.resolve("kilo-openrouter/minimax/minimax-m3.1-flash:free")[0].model,
                         "minimax/minimax-m3.1-flash:free")

    def test_fast_tag_follows_measurements(self):
        reg = llmf.Client(use_cache=False)._reg
        self.assertEqual([str(t.model) for t in reg.tag("fast")][:3],
                         ["minimax-m2.7", "codestral-latest", "llama3.1-8B"])
        self.assertEqual(reg.tag("best")[0].provider, "ch-at")
        self.assertEqual(reg.tag("best")[1].model, "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertNotIn("Meta-Llama-3_3-70B-Instruct", [t.model for t in reg.tag("fast")])


class Doctor(unittest.TestCase):
    def test_check_reports_each_model(self):
        c = llm(["ok", "err500", "err404", "empty", "reasoning"])
        seen = []
        res = c.models.check(on_result=seen.append)
        by = {r.model: r for r in res}
        self.assertEqual({k: v.ok for k, v in by.items()},
                         {"ok": True, "err500": False, "err404": False, "empty": False, "reasoning": True})
        self.assertIn("Echo", by["ok"].answer)
        self.assertIn("500", by["err500"].error)
        self.assertEqual(len(seen), 5)

    def test_provider_filter_and_limited_skipped(self):
        c = llm()
        c.register("lim", BASE + "/v1", "ok")
        c._reg.providers["lim"].checkable = False
        self.assertEqual({r.provider for r in c.models.check()}, {"fake"})
        self.assertEqual({r.provider for r in c.models.check(include_limited=True)}, {"fake", "lim"})
        self.assertEqual({r.provider for r in c.models.check(providers=["fake"])}, {"fake"})
        with self.assertRaises(llmf.ModelNotFound):
            c.models.check(providers=["nope"])

    def test_live_models_included_with_all(self):
        c = llm()
        spec = c._reg.providers["fake"]
        spec.base_url, spec.chat_path = BASE, "/v1/chat/completions"
        spec.models_path, spec.free_suffix = "/v1/models", ":free"
        names = {r.model for r in c.models.check(include_live=True)}
        self.assertEqual(names, {"ok", "a:free"})

    def test_cache_roundtrip_demotes_failures_and_seeds_latency(self):
        with tempfile.TemporaryDirectory() as d:
            c = LLMF(builtin=False, retries=0, cache_dir=d)
            c.register("bad", BASE + "/v1", "err500")
            c.register("good", BASE + "/v1", "ok")
            c.models.check()
            self.assertTrue(os.path.exists(os.path.join(d, "health.json")))
            c2 = LLMF(builtin=False, retries=0, cache_dir=d)           # fresh process-like client
            c2.register("bad", BASE + "/v1", "err500", front=True)     # ranked first...
            c2.register("good", BASE + "/v1", "ok")
            c2._state.seed(__import__("llmf._cache", fromlist=["x"]).load(d))
            self.assertEqual(c2._plan(None, None, False)[0].provider, "good")  # ...but demoted
            self.assertIsNotNone(c2._state.latency(llmf.client.Target("good", "ok")))

    def test_cache_disabled_and_stale(self):
        from llmf import _cache
        with tempfile.TemporaryDirectory() as d:
            _cache.save(d, [{"provider": "a", "model": "m", "ok": True, "latency": 1}])
            self.assertEqual(len(_cache.load(d)), 1)
            path = os.path.join(d, "health.json")
            with open(path) as f:
                data = json.load(f)
            data["checked_at"] -= 3 * 24 * 3600
            with open(path, "w") as f:
                json.dump(data, f)
            self.assertEqual(_cache.load(d), [])
        self.assertEqual(_cache.load(None), [])

    def test_partial_check_merges_into_cache(self):
        from llmf import _cache
        with tempfile.TemporaryDirectory() as d:
            c = LLMF(builtin=False, cache_dir=d)
            c.register("a", BASE + "/v1", "ok")
            c.register("b", BASE + "/v1", "ok")
            c.models.check(providers=["a"])
            c.models.check(providers=["b"])
            self.assertEqual({r["provider"] for r in _cache.load(d)}, {"a", "b"})


class Routing(unittest.TestCase):
    def test_adaptive_prefers_fastest_observed(self):
        c = llm(routing="adaptive")
        c.register("other", BASE + "/v1", "ok")
        T = llmf.client.Target
        c._state.ok(T("fake", "ok"), 3.0)
        c._state.ok(T("other", "ok"), 0.2)
        self.assertEqual(c._plan(None, None, False)[0].provider, "other")
        c.configure(routing="ranked")
        self.assertEqual(c._plan(None, None, False)[0].provider, "fake")
        with self.assertRaises(ValueError):
            c.configure(routing="whatever")

    def test_race_returns_first_success_even_if_first_provider_fails(self):
        c = LLMF(builtin=False, retries=0, use_cache=False, race=2)
        c.register("a", BASE + "/v1", "err500")
        c.register("b", BASE + "/v1", "ok")
        r = c.chat("hi")
        self.assertEqual((r, r.provider), ("Echo: hi", "b"))
        self.assertIn(True, [a.ok for a in r.attempts])
        deadline = time.monotonic() + 3   # the loser may still be in flight when the winner returns
        while len(r.attempts) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(sorted(a.ok for a in r.attempts), [False, True])

    def test_race_all_fail_then_continue(self):
        c = LLMF(builtin=False, retries=0, use_cache=False)
        for n, m in (("a", "err500"), ("b", "err404"), ("c", "ok")):
            c.register(n, BASE + "/v1", m)
        r = c.chat("hi", race=2)       # first batch (a,b) fails, second batch has c
        self.assertEqual(r.provider, "c")

    def test_race_per_call_and_exhaustion(self):
        c = LLMF(builtin=False, retries=0, use_cache=False)
        c.register("a", BASE + "/v1", "err500")
        c.register("b", BASE + "/v1", "err500")
        with self.assertRaises(llmf.AllProvidersFailed) as cm:
            c.chat("hi", race=2)
        self.assertEqual(len(cm.exception.errors), 2)


class ErrorKinds(unittest.TestCase):
    def kind(self, status, msg, code=None):
        e = llmf.ProviderError("p", "m", msg, status=status, code=code)
        return e.retryable, e.scope, e.cooldown

    def test_plain_rate_limit_vs_capacity_vs_paid(self):
        self.assertEqual(self.kind(429, "slow down"), (False, "provider", 60.0))
        self.assertEqual(self.kind(429, "ResourceExhausted: capacity"), (False, "model", 600.0))
        self.assertEqual(self.kind(200, "no capacity right now"), (False, "model", 600.0))
        r, scope, cd = self.kind(429, "use a paid model")
        self.assertEqual((r, scope), (False, "model"))
        self.assertGreaterEqual(cd, 3600)
        self.assertEqual(self.kind(500, "boom")[:2], (True, "provider"))

    def test_blockrun_capacity_message_is_not_treated_as_paid(self):
        msg = ("Free model capacity exhausted \u2014 retry shortly, or use a paid model (from $0.002/request). "
               "(NVIDIA API error: 503 ResourceExhausted)")
        self.assertEqual(self.kind(429, msg), (False, "model", 600.0))

    def test_retry_after_is_honoured(self):
        r, scope, cd = self.kind(429, "Rate limit exceeded. Retry after 1 seconds.")
        self.assertEqual(scope, "provider")
        self.assertLess(cd, 15)
        self.assertGreaterEqual(cd, 5)

    def test_capacity_on_one_model_does_not_sideline_the_provider(self):
        c = LLMF(builtin=False, retries=0, use_cache=False)
        c.register("p", BASE + "/v1", ["err429cap", "ok"])
        r = c.chat("hi", model=["p/err429cap", "p/ok"])
        self.assertEqual((r.model, r.attempts[0].ok), ("ok", False))
        self.assertGreater(c._state.ready_in(llmf.client.Target("p", "err429cap"), 0), 300)
        self.assertEqual(c._state.ready_in(llmf.client.Target("p", "ok"), 0), 0)

    def test_paid_model_429_sleeps_for_hours(self):
        c = LLMF(builtin=False, retries=0, use_cache=False)
        c.register("p", BASE + "/v1", ["err429paid", "ok"])
        c.chat("hi", model=["p/err429paid", "p/ok"])
        self.assertGreater(c._state.ready_in(llmf.client.Target("p", "err429paid"), 0), 3600)


class ChatOnlyAndFree(unittest.TestCase):
    def setUp(self):
        self.c = LLMF(builtin=False, use_cache=False)
        self.c.register("fake", BASE, "x", chat_path="/v1/chat/completions")
        self.c._reg.providers["fake"].models_path = "/v1/models"

    def test_live_list_skips_non_chat_guard_and_paid(self):
        ids = [m.id for m in self.c.models.list(live=True)]
        self.assertEqual(ids, ["x", "a:free", "b"])
        ids = [m.id for m in self.c.models.list(live=True, include_non_chat=True)]
        self.assertIn("whisper-large-v3", ids)
        self.assertIn("Qwen3Guard-8B", ids)
        self.assertNotIn("paid", ids)
        self.assertNotIn("priced", ids)

    def test_doctor_all_tests_only_chat_ids_by_default(self):
        names = {r.model for r in self.c.models.check(include_live=True)}
        self.assertEqual(names, {"x", "a:free", "b"})
        names = {r.model for r in self.c.models.check(include_live=True, include_non_chat=True)}
        self.assertIn("whisper-large-v3", names)

    def test_heuristics(self):
        from llmf.providers.base import is_chat_model
        for bad in ("whisper-large-v3", "Qwen3Guard-8B", "nvidia/nemotron-3.5-content-safety:free", "kokoro-tts",
                    "text-embedding-3-small", "flux-dev", "voxtral-mini", "kling-v2", "seedance-1"):
            self.assertFalse(is_chat_model(bad), bad)
        for bad in ("madlad", "realesrgan", "rmbg", "demucs", "deoldify", "step1x-edit", "sam"):
            self.assertFalse(is_chat_model(bad), bad)
        for good in ("moondream2", "qwen25-vl", "qwen3-coder", "gpt-oss:20b", "Qwen3.5-397B-A17B", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                     "deepseek-r1", "qwen-vl"):
            self.assertTrue(is_chat_model(good), good)
        self.assertFalse(is_chat_model("x", {"architecture": {"output_modalities": ["image"]}}))
        self.assertFalse(is_chat_model("x", {"categories": ["audio"]}))
        self.assertTrue(is_chat_model("x", {"categories": ["coding"]}))


class VisionTimeout(unittest.TestCase):
    def test_images_get_the_longer_timeout(self):
        c = LLMF(builtin=False, retries=0, use_cache=False, timeout=0.5, vision_timeout=5, deadline=20)
        c.register("p", BASE + "/v1", "slow", vision=True)
        with self.assertRaises(llmf.AllProvidersFailed):
            c.chat("hi")                                      # text: 0.5 s timeout < 1.2 s server delay
        r = c.chat("describe", images=["https://x/y.png"])    # vision: 5 s
        self.assertEqual(r.provider, "p")

    def test_doctor_gives_vision_models_longer(self):
        c = LLMF(builtin=False, use_cache=False)
        c.register("p", BASE + "/v1", "slow", vision=True)
        res = c.models.check(timeout=0.5, vision_timeout=5)
        self.assertTrue(res[0].ok)
        res = c.models.check(timeout=0.5, vision_timeout=0.5)
        self.assertFalse(res[0].ok)


class DynamicFast(unittest.TestCase):
    def test_fast_follows_measurements(self):
        c = LLMF(use_cache=False)
        T = llmf.client.Target
        c._state.ok(T("ovh", "Qwen3.5-9B"), 0.25)             # not in the static tag, but measured quick
        c._state.ok(T("llm7", "minimax-m2.7"), 0.9)
        c._state.ok(T("chatjimmy", "llama3.1-8B"), 0.1)
        plan = c._plan("fast", None, False)
        self.assertEqual([t.model for t in plan[:3]], ["llama3.1-8B", "Qwen3.5-9B", "minimax-m2.7"])

    def test_slow_measurement_is_not_added_and_failures_sink(self):
        c = LLMF(use_cache=False)
        T = llmf.client.Target
        c._state.ok(T("ovh", "Qwen3.5-9B"), 9.0)               # slow -> must not join "fast"
        c._state.seed([{"provider": "llm7", "model": "minimax-m2.7", "ok": False, "latency": 0}])
        plan = c._plan("fast", None, False)
        self.assertNotIn(T("ovh", "Qwen3.5-9B"), plan)
        self.assertEqual(plan[-1], T("llm7", "minimax-m2.7"))  # demoted: tried last

    def test_other_tags_stay_static(self):
        c = LLMF(use_cache=False)
        c._state.ok(llmf.client.Target("ovh", "Qwen3.5-9B"), 0.1)
        self.assertEqual(c._plan("best", None, False)[0].model, "gpt-4o")


class NewProviders(unittest.TestCase):
    def test_catalogue_entries(self):
        c = LLMF(use_cache=False)
        spec = c._reg.providers
        self.assertTrue(spec["rewind-ai"].chat_url.endswith("/v1/chat/completions/"))
        self.assertEqual(spec["rewind-ai"].headers["Origin"], "https://rewind.ai")
        self.assertEqual([m.id for m in spec["ch-at"].models], ["gpt-4o"])
        self.assertFalse(spec["nottrack"].auto)
        self.assertNotIn("nottrack", [t.provider for t in c._reg.chain()])
        self.assertEqual(c.models.resolve("gpt-4o")[0], "ch-at/gpt-4o")
        self.assertEqual(c.models.resolve("rewind/gpt-4o-mini")[0], "rewind-ai/gpt-4o-mini")
        with self.assertRaises(llmf.ModelNotFound):
            c.models.resolve("qwen-2.5-72b")   # sign-in only -> never picked by fuzzy matching
        self.assertEqual(spec["pollinations"].models[0].aliases[0], "openai-fast")
        self.assertEqual(c.models.resolve("blockrun")[0], "blockrun/nvidia/nemotron-3.5-lightning")

    def make(self, **kw):
        c = LLMF(builtin=False, retries=0, use_cache=False, **kw)
        c.register("nottrack", BASE, "debate", kind="nottrack", chat_path="/api/dispatch")
        return c

    def test_nottrack_joins_deltas_and_separates_speakers(self):
        r = self.make().chat("hi")
        self.assertEqual(str(r), "Hello\n\nWorld")
        self.assertEqual(r.provider, "nottrack")
        _path, body, _h = fakeserver.Handler.calls[-1]
        self.assertEqual(body, {"user_input": "hi"})

    def test_nottrack_transcript_for_multi_turn(self):
        self.make().chat([{"role": "user", "content": "I am Minh"}, {"role": "assistant", "content": "Hi"},
                          {"role": "user", "content": "Who am I?"}])
        body = fakeserver.Handler.calls[-1][1]
        self.assertEqual(body["user_input"], "User: I am Minh\nAssistant: Hi\nUser: Who am I?")

    def test_nottrack_stream_and_error_event(self):
        c = self.make()
        self.assertEqual("".join(c.stream("hi")), "Hello\n\nWorld")
        with self.assertRaises(llmf.AllProvidersFailed):
            c.chat("boom")


class Startup(unittest.TestCase):
    def test_import_is_lazy(self):
        code = ("import sys; sys.path.insert(0, %r); import llmf; "
                "print(sorted(m for m in ('asyncio','concurrent.futures','llmf.server','llmf._socks','ssl') "
                "if m in sys.modules))" % os.path.join(os.path.dirname(__file__), "..", "src"))
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                             env={**os.environ, "LLMF_NO_CACHE": "1"}).stdout.strip()
        self.assertNotIn("asyncio", out)
        self.assertNotIn("concurrent.futures", out)
        self.assertNotIn("llmf.server", out)
        self.assertNotIn("llmf._socks", out)


class CLIv03(unittest.TestCase):
    def run_cli(self, argv, c=None):
        import contextlib
        import io
        from llmf import cli
        llmf._default = c or llm(["ok", "err500"])
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        sys.stdin = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        finally:
            sys.stdin = old
            llmf._default = None
        return code, out.getvalue(), err.getvalue()

    def test_doctor(self):
        code, out, err = self.run_cli(["doctor", "--no-save"])
        self.assertEqual(code, 0)
        self.assertIn("OK    fake/ok", out)
        self.assertIn("FAIL  fake/err500", out)
        self.assertIn("1 ok, 1 failed", err)

    def test_doctor_json_and_models_check_alias(self):
        code, out, _ = self.run_cli(["models", "check", "--json", "--no-save"])
        self.assertEqual({r["name"]: r["ok"] for r in json.loads(out)},
                         {"fake/ok": True, "fake/err500": False})

    def test_models_list_and_resolve_and_providers(self):
        _, out, _ = self.run_cli(["models"])
        self.assertIn("MODEL", out)
        self.assertIn("fake/ok", out)
        _, out, _ = self.run_cli(["models", "resolve", "fake/ok"])
        self.assertEqual(out.strip(), "fake/ok")
        _, out, _ = self.run_cli(["providers"])
        self.assertIn("PROVIDER", out)
        self.assertEqual(self.run_cli(["models", "bogus"])[0], 2)

    def test_ask_subcommand_race_routing_flags(self):
        code, out, _ = self.run_cli(["ask", "hello", "--race", "2", "--routing", "adaptive", "-m", "fake/ok"])
        self.assertEqual((code, out.strip()), (0, "Echo: hello"))


if __name__ == "__main__":
    unittest.main()
