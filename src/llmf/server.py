"""``llmf serve`` - a local OpenAI-compatible HTTP server backed by llmf.

Point any OpenAI client at ``http://127.0.0.1:8000/v1`` (any api key) and it will
use the free endpoints, with fallback. Stdlib only.

Security defaults: binds to localhost, no CORS, optional bearer key.
"""

from __future__ import annotations

import hmac
import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .client import Client
from .errors import AllProvidersFailed, LLMFError, ModelNotFound

MAX_BODY = 20 * 1024 * 1024  # base64 images can be large
ALIASES = ("auto", "fast", "best", "code", "vision", "reasoning")


class _Config:
    def __init__(self, client: Client, api_key: Optional[str], cors: bool,
                 strict_models: bool, fallback: bool) -> None:
        self.client, self.api_key, self.cors = client, api_key, cors
        self.strict_models, self.fallback = strict_models, fallback


def _err(message: str, etype: str, code: Optional[str] = None) -> Dict[str, Any]:
    return {"error": {"message": message, "type": etype, "code": code}}


def make_handler(cfg: _Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "llmf"
        protocol_version = "HTTP/1.0"  # one request per connection; streams end on close

        def log_message(self, fmt, *args):  # quiet by default
            pass

        # ------------------------------------------------------------ helpers
        def _headers(self, code: int, ctype: str, length: Optional[int] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            if cfg.cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def _json(self, code: int, obj: Any) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self._headers(code, "application/json", len(data))
            self.wfile.write(data)

        def _authorised(self) -> bool:
            if not cfg.api_key:
                return True
            got = self.headers.get("Authorization", "")
            return hmac.compare_digest(got.encode(), ("Bearer " + cfg.api_key).encode())

        def _route(self) -> str:
            path = self.path.split("?", 1)[0].rstrip("/")
            return path[3:] if path.startswith("/v1") else path

        # -------------------------------------------------------------- verbs
        def do_OPTIONS(self):
            self._headers(204 if cfg.cors else 405, "text/plain", 0)

        def do_GET(self):
            route = self._route()
            if route in ("", "/health"):
                return self._json(200, {"status": "ok", "service": "llmf"})
            if not self._authorised():
                return self._json(401, _err("invalid api key", "invalid_request_error", "invalid_api_key"))
            if route == "/models":
                now = int(time.time())
                ids = list(ALIASES) + [m.name for m in cfg.client.models()]
                return self._json(200, {"object": "list", "data": [
                    {"id": i, "object": "model", "created": now, "owned_by": "llmf"} for i in ids]})
            self._json(404, _err("not found: %s" % self.path, "invalid_request_error", "not_found"))

        def do_POST(self):
            if self._route() != "/chat/completions":
                return self._json(404, _err("not found: %s" % self.path,
                                            "invalid_request_error", "not_found"))
            if not self._authorised():
                return self._json(401, _err("invalid api key", "invalid_request_error", "invalid_api_key"))
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._json(411, _err("Content-Length required", "invalid_request_error"))
            if n > MAX_BODY:
                return self._json(413, _err("request too large", "invalid_request_error"))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                msgs = body["messages"]
                if not isinstance(msgs, list) or not msgs:
                    raise ValueError("messages must be a non-empty list")
            except (ValueError, KeyError, TypeError) as e:
                return self._json(400, _err("bad request: %s" % e, "invalid_request_error"))
            try:
                self._chat(body, msgs)
            except (BrokenPipeError, ConnectionResetError):
                pass

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

        def _chat(self, body: dict, msgs: list) -> None:
            try:
                model = self._model(body.get("model"))
            except ModelNotFound as e:
                return self._json(404, _err(str(e), "invalid_request_error", "model_not_found"))
            kw: Dict[str, Any] = {"model": model, "fallback": True if cfg.fallback else None,
                                  "max_tokens": body.get("max_tokens") or body.get("max_completion_tokens"),
                                  "temperature": body.get("temperature"), "top_p": body.get("top_p"),
                                  "tools": body.get("tools") or None}
            if body.get("stop") is not None:
                kw["stop"] = body["stop"]
            rf = body.get("response_format")
            kw["json"] = isinstance(rf, dict) and rf.get("type") in ("json_object", "json_schema")
            cid, created = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time())
            try:
                if body.get("stream"):
                    return self._stream(msgs, kw, cid, created)
                r = cfg.client.chat(msgs, **kw)
            except AllProvidersFailed as e:
                return self._json(502, _err(str(e), "upstream_error", "all_providers_failed"))
            except (LLMFError, ValueError) as e:
                return self._json(400, _err(str(e), "invalid_request_error"))
            message: Dict[str, Any] = {"role": "assistant", "content": r.text}
            if r.reasoning:
                message["reasoning"] = r.reasoning
            if r.tool_calls:
                message["tool_calls"] = r.tool_calls
            usage = r.usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            self._json(200, {"id": cid, "object": "chat.completion", "created": created,
                             "model": r.source, "choices": [{"index": 0, "message": message,
                                                              "finish_reason": r.finish_reason or "stop"}],
                             "usage": usage})

        def _stream(self, msgs: list, kw: dict, cid: str, created: int) -> None:
            st = cfg.client.stream(msgs, **kw)
            it = iter(st)
            try:
                first = next(it)  # fallback happens here, before any bytes are sent
            except StopIteration:
                return self._json(502, _err("empty answer", "upstream_error", "empty"))
            self._headers(200, "text/event-stream")

            def send(delta: dict, finish: Optional[str] = None) -> None:
                chunk = {"id": cid, "object": "chat.completion.chunk", "created": created,
                         "model": "%s/%s" % (st.provider, st.model),
                         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n")
                self.wfile.flush()

            send({"role": "assistant", "content": ""})
            send({"content": first})
            try:
                for piece in it:
                    send({"content": piece})
                send({}, "stop")
            except LLMFError as e:
                self.wfile.write(b"data: " + json.dumps(_err(str(e), "upstream_error")).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return Handler


def make_server(client: Client, host: str = "127.0.0.1", port: int = 8000, *,
                api_key: Optional[str] = None, cors: bool = False,
                strict_models: bool = False, fallback: bool = True) -> ThreadingHTTPServer:
    cfg = _Config(client, api_key, cors, strict_models, fallback)
    srv = ThreadingHTTPServer((host, port), make_handler(cfg))
    srv.daemon_threads = True
    return srv


def serve(client: Client, host: str = "127.0.0.1", port: int = 8000, **kw: Any) -> None:
    srv = make_server(client, host, port, **kw)
    h, p = srv.server_address[:2]
    if host not in ("127.0.0.1", "localhost", "::1") and not kw.get("api_key"):
        print("warning: listening on %s without --api-key: anyone who can reach this "
              "port can spend your free quota." % host, file=sys.stderr)
    print("llmf serving on http://%s:%s/v1  (Ctrl+C to stop)" % (h, p), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
