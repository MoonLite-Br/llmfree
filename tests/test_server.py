import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import fakeserver  # noqa: E402
import llmf  # noqa: E402
from llmf.server import make_server  # noqa: E402

UP, UPBASE = fakeserver.start()


def start(**kw):
    c = llmf.Client(builtin=False, deadline=10, retries=0)
    c.register("fake", UPBASE + "/v1", ["ok", "streamthink", "err500"])
    srv = make_server(c, "127.0.0.1", 0, **kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def call(url, body=None, headers=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_health_and_models(self):
        self.assertEqual(json.loads(call(self.base + "/health")[1])["status"], "ok")
        ids = [m["id"] for m in json.loads(call(self.base + "/v1/models")[1])["data"]]
        self.assertIn("fast", ids)
        self.assertIn("fake/ok", ids)

    def test_chat_non_stream(self):
        st, body, _ = call(self.base + "/v1/chat/completions", {
            "model": "fake/ok", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50,
            "temperature": 0.1})
        j = json.loads(body)
        self.assertEqual(st, 200)
        self.assertEqual(j["object"], "chat.completion")
        self.assertEqual(j["choices"][0]["message"]["content"], "Echo: hi")
        self.assertEqual(j["model"], "fake/ok")
        self.assertEqual(j["usage"]["total_tokens"], 3)
        up = fakeserver.Handler.calls[-1][1]
        self.assertEqual((up["max_tokens"], up["temperature"]), (50, 0.1))

    def test_path_without_v1_and_unknown_model_lenient(self):
        st, body, _ = call(self.base + "/chat/completions", {
            "model": "gpt-4o", "messages": [{"role": "user", "content": "yo"}]})
        self.assertEqual((st, json.loads(body)["choices"][0]["message"]["content"]), (200, "Echo: yo"))

    def test_stream_sse(self):
        st, body, hdr = call(self.base + "/v1/chat/completions", {
            "model": "fake/streamthink", "stream": True,
            "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(st, 200)
        self.assertIn("text/event-stream", hdr["Content-Type"])
        events = [e[6:] for e in body.split("\n\n") if e.startswith("data: ")]
        self.assertEqual(events[-1], "[DONE]")
        chunks = [json.loads(e) for e in events[:-1]]
        text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
        self.assertEqual(text, "Hello world")
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(chunks[0]["choices"][0]["delta"]["role"], "assistant")

    def test_errors(self):
        self.assertEqual(call(self.base + "/v1/nope")[0], 404)
        st, body, _ = call(self.base + "/v1/chat/completions", {"messages": []})
        self.assertEqual(st, 400)
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=b"{oops",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)
        req = {"model": "fake/err500", "messages": [{"role": "user", "content": "x"}]}
        st, body, _ = call(self.base + "/v1/chat/completions", req)
        self.assertEqual(st, 200)  # default: falls back to a working model
        self.assertEqual(json.loads(body)["model"], "fake/ok")
        srv, base = start(fallback=False)
        try:
            st, body, _ = call(base + "/v1/chat/completions", req)
            self.assertEqual(st, 502)
            self.assertEqual(json.loads(body)["error"]["code"], "all_providers_failed")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_no_cors_by_default(self):
        _, _, hdr = call(self.base + "/health")
        self.assertNotIn("Access-Control-Allow-Origin", hdr)


class Options(unittest.TestCase):
    def test_api_key(self):
        srv, base = start(api_key="sekret")
        try:
            body = {"messages": [{"role": "user", "content": "hi"}]}
            self.assertEqual(call(base + "/v1/chat/completions", body)[0], 401)
            self.assertEqual(call(base + "/v1/models", headers={"Authorization": "Bearer nope"})[0], 401)
            ok = call(base + "/v1/chat/completions", body, {"Authorization": "Bearer sekret"})
            self.assertEqual(ok[0], 200)
            self.assertEqual(call(base + "/health")[0], 200)  # health stays open
        finally:
            srv.shutdown()
            srv.server_close()

    def test_cors_and_strict(self):
        srv, base = start(cors=True, strict_models=True)
        try:
            st, _, hdr = call(base + "/v1/chat/completions", method="OPTIONS")
            self.assertEqual((st, hdr["Access-Control-Allow-Origin"]), (204, "*"))
            st, body, _ = call(base + "/v1/chat/completions", {
                "model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]})
            self.assertEqual(st, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "model_not_found")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_vision_messages_pass_through(self):
        srv, base = start()
        try:
            msg = [{"role": "user", "content": [{"type": "text", "text": "see"},
                                                {"type": "image_url", "image_url": {"url": "https://x/y.png"}}]}]
            self.assertEqual(call(base + "/v1/chat/completions", {"model": "fake/ok", "messages": msg})[0], 200)
            self.assertEqual(fakeserver.Handler.calls[-1][1]["messages"][0]["content"][1]["image_url"]["url"],
                             "https://x/y.png")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
