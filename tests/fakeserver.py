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

    def do_GET(self):
        if self.path.endswith("/models"):
            self._send(200, json.dumps({"data": [
                {"id": "a:free"}, {"id": "b"}, {"id": "paid", "billing_mode": "paid"}]}))
        else:
            self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        Handler.calls.append((self.path, body, dict(self.headers)))
        if self.path == "/api/chat":
            return self._jimmy(body)
        return self._openai(body)

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
