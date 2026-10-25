"""Adapter for nottrack.com ``/api/dispatch`` (SSE, multi-speaker "debate" mode).

Request: ``{"user_input": "..."}``. Response: server-sent events; the answer is the
concatenation of ``chunk`` fields of ``type == "delta"`` events. Replies are long,
uncensored, role-play style, with several speakers, so this provider is opt-in only
(``provider="nottrack"``) and never part of the automatic chain.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, List, Optional

from .. import _http
from ..errors import ProviderError
from .base import Adapter, Completion, Options, ProviderSpec, translate


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return "" if content is None else str(content)


def build_input(messages: List[dict]) -> str:
    """The endpoint takes one string: send a lone user message as is, else a transcript."""
    if len(messages) == 1:
        return _text(messages[0].get("content"))
    names = {"system": "System", "user": "User", "assistant": "Assistant"}
    lines = ["%s: %s" % (names.get(m.get("role"), "User"), _text(m.get("content"))) for m in messages]
    return "\n".join(lines)


class NotTrackAdapter(Adapter):
    def _open(self, spec, messages, opts, timeout):
        body = json.dumps({"user_input": build_input(messages)}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
                   "User-Agent": opts.user_agent}
        headers.update(spec.headers)
        return _http.open_url(spec.chat_url, headers=headers, data=body, timeout=timeout, proxy=opts.proxy)

    def _events(self, spec, model, resp) -> Iterator[str]:
        """Yield text pieces; a blank line is added when the speaker changes."""
        speaker: Optional[str] = None
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                ev = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            kind = ev.get("type")
            if kind == "error":
                raise ProviderError(spec.name, model, str(ev.get("message") or ev.get("error") or "error event"),
                                    status=502, code="event_error")
            if kind != "delta":
                continue
            chunk = ev.get("chunk")
            if not chunk:
                continue
            who = ev.get("speaker")
            if speaker is not None and who != speaker:
                yield "\n\n"
            speaker = who
            yield str(chunk)

    def complete(self, spec, model, messages, opts, timeout) -> Completion:
        with translate(spec, model):
            resp = self._open(spec, messages, opts, timeout)
            try:
                text = "".join(self._events(spec, model, resp)).strip()
            finally:
                resp.close()
        if not text:
            raise ProviderError(spec.name, model, "empty answer", status=200, code="empty")
        return Completion(text=text, finish_reason="stop")

    def stream(self, spec, model, messages, opts, timeout) -> Iterator[str]:
        with translate(spec, model):
            resp = self._open(spec, messages, opts, timeout)
        try:
            started = False
            it = self._events(spec, model, resp)
            while True:
                with translate(spec, model):
                    piece = next(it, None)
                if piece is None:
                    break
                if not started:
                    piece = piece.lstrip()
                if piece:
                    started = True
                    yield piece
            if not started:
                raise ProviderError(spec.name, model, "empty stream", status=200, code="empty")
        finally:
            resp.close()

    def list_models(self, spec, timeout, user_agent=_http.DEFAULT_UA, proxy=None, chat_only=True):
        return []
