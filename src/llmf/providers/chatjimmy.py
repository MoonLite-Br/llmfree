"""Adapter for chatjimmy.ai (raw text + ``<|stats|>{json}<|/stats|>`` trailer)."""

from __future__ import annotations

import codecs
import json
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import _http
from ..errors import ProviderError
from .base import Adapter, Completion, Options, ProviderSpec, parse_model_list, translate

STATS_OPEN = "<|stats|>"
STATS_CLOSE = "<|/stats|>"
# Greedy first group => the *last* stats block wins, so a prompt that makes the
# model print the sentinel cannot truncate the answer.
_TRAILER = re.compile(r"(.*)<\|stats\|>(.*?)<\|/stats\|>\s*", re.DOTALL)


def split_stats(raw: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    m = _TRAILER.fullmatch(raw)
    if not m:
        return raw.strip(), None
    try:
        stats = json.loads(m.group(2))
    except ValueError:
        stats = None
    return m.group(1).strip(), stats if isinstance(stats, dict) else None


def _usage(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not stats:
        return None
    p, c = stats.get("prefill_tokens"), stats.get("decode_tokens")
    if p is None and c is None:
        return None
    return {"prompt_tokens": p, "completion_tokens": c,
            "total_tokens": stats.get("total_tokens") or ((p or 0) + (c or 0))}


class ChatJimmyAdapter(Adapter):
    def _request(self, spec: ProviderSpec, model: str, messages: List[dict],
                 opts: Options, stream: bool):
        options: Dict[str, Any] = {"selectedModel": model}
        if opts.temperature is not None:
            options["temperature"] = opts.temperature
        if opts.max_tokens is not None:
            options["max_tokens"] = opts.max_tokens
        body = {"chatOptions": options, "messages": [_plain(m) for m in messages],
                "stream": bool(stream)}
        headers = {"Content-Type": "application/json", "User-Agent": opts.user_agent}
        headers.update(spec.headers)
        return spec.chat_url, headers, json.dumps(body).encode("utf-8")

    def complete(self, spec, model, messages, opts, timeout) -> Completion:
        url, headers, data = self._request(spec, model, messages, opts, False)
        with translate(spec, model):
            resp = _http.open_url(url, headers=headers, data=data, timeout=timeout, proxy=opts.proxy)
            try:
                raw = _http.decode_body(resp)
            finally:
                resp.close()
        text, stats = split_stats(raw)
        if not text:
            raise ProviderError(spec.name, model, "empty answer", status=200, code="empty")
        reason = (stats or {}).get("done_reason")
        return Completion(text=text, usage=_usage(stats), finish_reason=reason or "stop",
                          raw={"text": raw, "stats": stats})

    def stream(self, spec, model, messages, opts, timeout) -> Iterator[str]:
        url, headers, data = self._request(spec, model, messages, opts, True)
        with translate(spec, model):
            resp = _http.open_url(url, headers=headers, data=data, timeout=timeout, proxy=opts.proxy)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buf = ""          # not-yet-emitted text
        holding = False   # a stats sentinel was seen; everything after is held
        started = False
        keep = len(STATS_OPEN) - 1
        try:
            while True:
                with translate(spec, model):
                    chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
                if not chunk:
                    break
                buf += decoder.decode(chunk)
                if holding:
                    continue
                i = buf.find(STATS_OPEN)
                if i >= 0:
                    out, buf, holding = buf[:i], buf[i:], True
                else:
                    cut = max(0, len(buf) - keep)
                    out, buf = buf[:cut], buf[cut:]
                if not started:
                    out = out.lstrip()
                if out:
                    started = True
                    yield out
            buf += decoder.decode(b"", final=True)
        finally:
            resp.close()
        # Stream finished: ``buf`` is either a stats trailer, plain tail text, or
        # (rarely) a fake sentinel from the model followed by the real trailer.
        text, _stats = split_stats(buf) if holding else (buf, None)
        if holding and _TRAILER.fullmatch(buf) is None:
            text = buf
        tail = text if started else text.lstrip()
        if tail.strip() or (tail and started):
            yield tail.rstrip() if holding else tail
        elif not started:
            raise ProviderError(spec.name, model, "empty answer", status=200, code="empty")


def _plain(message: dict) -> dict:
    """ChatJimmy takes plain-text content only; flatten content parts."""
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return {"role": message.get("role", "user"), "content": content or ""}
