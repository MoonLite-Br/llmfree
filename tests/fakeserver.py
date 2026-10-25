"""A local server that mimics the response shapes documented for each provider."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JIMMY_STATS = '<|stats|>{"done":true,"done_reason":"stop","prefill_tokens":5,"decode_tokens":7}<|/stats|>'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = []  # (path, body dict)

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    sessions = 0

    def do_GET(self):
        if self.path == "/chat":
            Handler.sessions += 1
            html = '<html><head><meta name="csrf-token" content="TOK%d"></head></html>' % Handler.sessions
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", "chataiorg_session=S%d; Path=/" % Handler.sessions)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.endswith("/models"):
            self._send(200, json.dumps({"data": [
                {"id": "a:free"}, {"id": "b"}, {"id": "paid", "billing_mode": "paid"},
                {"id": "whisper-large-v3"}, {"id": "Qwen3Guard-8B"}, {"id": "emb", "type": "embedding"},
                {"id": "priced", "pricing": {"prompt": "0.001", "completion": "0.002"}}]}))
        else:
            self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        Handler.calls.append((self.path, body, dict(self.headers)))
        if self.path == "/api/dispatch":
            return self._nottrack(body)
        if self.path.startswith("/v1/chat/completions/") and not self.headers.get("Origin"):
            return self._send(403, '{"error":"origin required"}')
        if self.path == "/api/chat" and "chatOptions" not in body:
            return self._chatai(body)
        if self.path == "/api/chat":
            return self._jimmy(body)
        if self.path == "/identity/guest":
            Handler.guests = getattr(Handler, "guests", 0) + 1
            return self._send(200, json.dumps({"token": "G%d" % Handler.guests}))
        if self.path == "/threads":
            return self._send(200, json.dumps({"thread_id": "t1"}))
        if self.path.endswith("/runs/wait"):
            return self._langchain(body)
        return self._openai(body)

    # -- nottrack: SSE with several speakers; "user_input" is the only accepted field
    def _nottrack(self, body):
        if "user_input" not in body:
            return self._send(400, '{"error":"bad request"}')
        ev = [{"type": "chat_meta", "chat_id": "c1", "mode": "debate"},
              {"type": "user", "turn": 0, "content": body["user_input"]},
              {"type": "thinking", "speaker": "A", "turn": 1},
              {"type": "delta", "speaker": "A", "turn": 1, "chunk": "Hel"},
              {"type": "delta", "speaker": "A", "turn": 1, "chunk": "lo"},
              {"type": "delta", "speaker": "B", "turn": 2, "chunk": "World"}]
        if body["user_input"] == "boom":
            ev = [{"type": "error", "message": "upstream down"}]
        data = "".join("data: " + json.dumps(e) + "\n\n" for e in ev)
        self._send(200, data, "text/event-stream")

    # -- chatai: needs the cookie + matching CSRF header from GET /chat
    def _chatai(self, body):
        cookie = self.headers.get("Cookie", "")
        tok = self.headers.get("X-CSRF-Token", "")
        if not cookie.startswith("chataiorg_session=S") or tok != "TOK" + cookie.split("=S")[1][:1]:
            return self._send(419, '{"message":"CSRF token mismatch"}')
        if body["model"] == "limited":
            return self._send(429, '{"error": "Free daily limit reached. Please try again tomorrow."}')
        data = "".join("data: " + json.dumps({"choices": [{"delta": {"content": p}}]}) + "\n\n"
                       for p in ("chat", "ai ", "ok")) + "data: [DONE]\n\n"
        self._send(200, data, "text/event-stream")

    # -- langchain docs agent
    def _langchain(self, body):
        if self.headers.get("Authorization") != "Bearer G%d" % getattr(Handler, "guests", 0):
            return self._send(401, "{}")
        q = body["input"]["messages"][0]["content"]
        if "weather" in q:
            msgs = [{"type": "ai", "content": "outside my scope"}]
            return self._send(200, json.dumps({"messages": msgs, "off_topic_query": True}))
        msgs = [{"type": "human", "content": q},
                {"type": "ai", "content": "", "tool_calls": [{"name": "search"}]},
                {"type": "tool", "content": "x"},
                {"type": "ai", "content": [{"type": "text", "text": "Use create_agent."}],
                 "usage_metadata": {"input_tokens": 9}}]
        self._send(200, json.dumps({"messages": msgs}))

    # -- chatjimmy
    def _jimmy(self, body):
        model = body["chatOptions"]["selectedModel"]
        text = "Hello from jimmy"
        if model == "tricky":
            text = "I print <|stats|> in my text"
        if body.get("stream"):
            data = (text + JIMMY_STATS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for i in range(0, len(data), 7):  # awkward chunk boundaries on purpose
                self.wfile.write(data[i:i + 7])
                self.wfile.flush()
            self.close_connection = True
            return
        self._send(200, "  " + text + JIMMY_STATS, "text/plain")

    # -- openai-compatible
    def _completion(self, content, **msg):
        message = {"role": "assistant", "content": content}
        message.update(msg)
        return json.dumps({"id": "x", "object": "chat.completion", "model": "m",
                           "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})

    def _openai(self, body):
        model = body["model"]
        if model == "slow":
            import time as _t
            _t.sleep(1.2)
        if model == "err429cap":
            return self._send(429, '{"error":{"message":"ResourceExhausted: no capacity for this model"}}')
        if model == "err429paid":
            return self._send(429, '{"error":{"message":"Free quota exhausted, please use a paid model"}}')
        if model == "err500":
            return self._send(500, '{"error":"boom"}')
        if model == "err429":
            return self._send(429, '{"error":{"message":"slow down","type":"rate_limit_error"}}')
        if model == "err404":
            return self._send(404, '{"error_type":"model_not_found","message":"nope"}')
        if model == "err200":
            return self._send(200, '{"error":{"message":"upstream","code":"FREE_MODEL_FAILED"},'
                                   '"debug":"Provider timeout: exceeded 12s"}')
        if model == "empty":
            return self._send(200, self._completion(None))
        if model == "reasoning":
            return self._send(200, self._completion("\n\nPong", reasoning="thinking..."))
        if model == "think":
            return self._send(200, self._completion("<think>hmm</think>\n\nAnswer"))
        if model == "badjson":
            return self._send(200, "<html>oops</html>", "text/html")
        if body.get("stream"):
            if model == "nostream":  # ignores stream flag
                return self._send(200, self._completion("whole"))
            if model == "streamerr":
                return self._send(500, '{"error":"x"}')
            pieces = ["He", "llo ", "<thi", "nk>zz</th", "ink>wor", "ld"] if model == "streamthink" \
                else ["Hel", "lo ", "wor", "ld"]
            lines = []
            for p in pieces:
                lines.append("data: " + json.dumps({"choices": [{"delta": {"content": p}}]}))
            lines.append('data: {"choices":[],"usage":{}}')
            lines.append("data: [DONE]")
            return self._send(200, "\n\n".join(lines) + "\n\n", "text/event-stream")
        self._send(200, self._completion("Echo: " + body["messages"][-1]["content"]
                                         if isinstance(body["messages"][-1]["content"], str)
                                         else "multipart"))


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]
