"""Adapter for apifreellm.com community API (``POST /api/chatAPI``, plain-text answer).

Stateless single-turn: the server ignores history, the ``model`` field and every generation option,
so a conversation is flattened into one prompt. Community rate limit: 5 requests per 20 s per IP.
"""

from __future__ import annotations

import json
from typing import Iterator

from .. import _http
from ..errors import ProviderError
from .base import Adapter, Completion, error_from_body, translate
from .nottrack import build_input


class ApiFreeAdapter(Adapter):
    def complete(self, spec, model, messages, opts, timeout) -> Completion:
        body = json.dumps({"inputCode": [{"role": "user", "content": build_input(messages)}],
                           "model": model, "userEmail": None, "isPremium": False}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "*/*", "User-Agent": opts.user_agent}
        headers.update(spec.headers)
        with translate(spec, model):
            resp = _http.open_url(spec.chat_url, headers=headers, data=body, timeout=timeout, proxy=opts.proxy)
            try:
                text = _http.decode_body(resp).strip()
            finally:
                resp.close()
        if text.startswith("{") and '"error"' in text[:40]:      # an error hidden in a 200
            code, msg = error_from_body(text)
            raise ProviderError(spec.name, model, msg, status=429 if "limit" in (code or "") else 502, code=code)
        if not text:
            raise ProviderError(spec.name, model, "empty answer", status=200, code="empty")
        return Completion(text=text, finish_reason="stop")

    def stream(self, spec, model, messages, opts, timeout) -> Iterator[str]:
        yield self.complete(spec, model, messages, opts, timeout).text      # one piece: no real streaming

    def list_models(self, spec, timeout, user_agent=_http.DEFAULT_UA, proxy=None, chat_only=True):
        return []
