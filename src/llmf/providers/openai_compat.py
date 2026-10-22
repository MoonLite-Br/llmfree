"""Adapter for OpenAI-compatible ``/chat/completions`` endpoints."""

from __future__ import annotations

import json
from typing import Any, Iterator, List, Optional

from .. import _http
from .._think import ThinkSplitter, split_think
from ..errors import ProviderError
from .base import Adapter, Completion, Options, ProviderSpec, error_from_body, translate


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


class OpenAIAdapter(Adapter):
    def _request(self, spec: ProviderSpec, model: str, messages: List[dict],
                 opts: Options, stream: bool):
        body: dict = {"model": model, "messages": messages}
        if opts.max_tokens is not None:
            body["max_tokens"] = opts.max_tokens
        if opts.temperature is not None:
            body["temperature"] = opts.temperature
        if opts.top_p is not None:
            body["top_p"] = opts.top_p
        if opts.stop is not None:
            body["stop"] = opts.stop
        if opts.json:
            body["response_format"] = {"type": "json_object"}
        if opts.tools:
            body["tools"] = opts.tools
        if stream:
            body["stream"] = True
        body.update(opts.extra)
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "User-Agent": opts.user_agent,
        }
        headers.update(spec.headers)
        return spec.chat_url, headers, json.dumps(body).encode("utf-8")

    # ------------------------------------------------------------------ complete
    def complete(self, spec, model, messages, opts, timeout) -> Completion:
        url, headers, data = self._request(spec, model, messages, opts, False)
        with translate(spec, model):
            resp = _http.open_url(url, headers=headers, data=data, timeout=timeout)
            try:
                text = _http.decode_body(resp)
            finally:
                resp.close()
            return self._parse(spec, model, json.loads(text))

    def _parse(self, spec: ProviderSpec, model: str, obj: Any) -> Completion:
        if not isinstance(obj, dict):
            raise ValueError("response is not a JSON object")
        # Some gateways report failures with HTTP 200 and an ``error`` body.
        if obj.get("error") or (obj.get("code") and not obj.get("choices")):
            code, msg = error_from_body(json.dumps(obj))
            status = 502 if code == "FREE_MODEL_FAILED" else 400
            raise ProviderError(spec.name, model, msg or "error response", code=code, status=status)
        choice = obj["choices"][0]
        msg = choice.get("message") or {}
        text = _content_to_text(msg.get("content"))
        reasoning = msg.get("reasoning") or msg.get("reasoning_content") or None
        if isinstance(reasoning, list):
            reasoning = _content_to_text(reasoning) or None
        text, think = split_think(text)
        if think:
            reasoning = ("%s\n%s" % (reasoning, think)).strip() if reasoning else think
        finish = choice.get("finish_reason")
        tool_calls = msg.get("tool_calls") or None
        if not text and not tool_calls:
            raise ProviderError(
                spec.name, model,
                "empty answer (finish_reason=%s); try a larger max_tokens" % finish,
                status=200, code="empty",
            )
        return Completion(text=text, reasoning=reasoning, usage=obj.get("usage"),
                          finish_reason=finish, tool_calls=tool_calls, raw=obj)

    # -------------------------------------------------------------------- stream
    def stream(self, spec, model, messages, opts, timeout) -> Iterator[str]:
        url, headers, data = self._request(spec, model, messages, opts, True)
        with translate(spec, model):
            resp = _http.open_url(url, headers=headers, data=data, timeout=timeout)
        try:
            splitter = ThinkSplitter()
            lines = iter(resp)
            first: Optional[str] = None
            for raw in lines:
                first = raw.decode("utf-8", "replace").strip()
                if first:
                    break
            if first is None:
                return
            if not first.startswith(("data:", ":", "event:", "id:", "retry:")):
                # Provider ignored ``stream`` and sent one JSON document.
                with translate(spec, model):
                    rest = "".join(r.decode("utf-8", "replace") for r in lines)
                    comp = self._parse(spec, model, json.loads(first + rest))
                yield comp.text
                return
            pending: Optional[str] = first
            while True:
                if pending is None:
                    with translate(spec, model):
                        nxt = next(lines, None)
                    if nxt is None:
                        break
                    line = nxt.decode("utf-8", "replace").strip()
                else:
                    line, pending = pending, None
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                with translate(spec, model):
                    obj = json.loads(payload)
                    if isinstance(obj, dict) and obj.get("error"):
                        code, msg = error_from_body(payload)
                        raise ProviderError(spec.name, model, msg, code=code, status=502)
                    choices = obj.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    piece = _content_to_text(delta.get("content"))
                if piece:
                    out = splitter.feed(piece)
                    if out:
                        yield out
            tail = splitter.flush()
            if tail:
                yield tail
        finally:
            resp.close()
