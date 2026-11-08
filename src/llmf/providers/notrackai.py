"""Adapter for notrack.ai (cookie bootstrap with ``GET /chat``, then SSE ``POST /api/dispatch``).

Anonymous and keyless; the server calls its model ``notrack-uncensored`` and takes an internal alias
(``C``). Each request starts a fresh chat (``chat_id: null``) and a conversation is flattened into one
``user_input``. Persona (``concise|normal|detailed|creative``) can be set with ``persona="..."`` as a call keyword.
"""

from __future__ import annotations

import http.cookiejar
import json
import threading
import time
import urllib.request
from typing import Dict, Iterator, Optional, Tuple

from .. import _http
from ..errors import ProviderError
from .base import Completion, translate
from .nottrack import NotTrackAdapter, build_input

SESSION_TTL = 600.0     # si_ses_id lives ~15 min
PERSONAS = ("concise", "normal", "detailed", "creative")


class NotTrackAIAdapter(NotTrackAdapter):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[Tuple[Optional[str], str], Tuple[urllib.request.OpenerDirector, float]] = {}

    def _opener(self, spec, ua, timeout, proxy, force=False):
        key = (proxy, spec.base_url)
        with self._lock:
            got = self._sessions.get(key)
            if got and time.monotonic() - got[1] < SESSION_TTL and not force:
                return got[0]
        jar = http.cookiejar.CookieJar()
        opener = _http.build_opener(proxy, urllib.request.HTTPCookieProcessor(jar))
        resp = _http.open_url(spec.base_url.rstrip("/") + "/chat",
                              headers={"User-Agent": ua, "Accept": "text/html,*/*"}, timeout=timeout, opener=opener)
        try:
            resp.read(65536)
        finally:
            resp.close()
        with self._lock:
            self._sessions[key] = (opener, time.monotonic())
        return opener

    def _open(self, spec, messages, opts, timeout):
        persona = (opts.extra or {}).get("persona", "normal")
        body = json.dumps({
            "user_input": build_input(messages), "mode": "usual", "model": "C",
            "persona": persona if persona in PERSONAS else "normal", "max_turns": 6, "chat_id": None,
            "attachments": [], "regenerate": False, "edit": False, "edit_mid": None, "via": "typed",
        }).encode("utf-8")
        base = spec.base_url.rstrip("/")
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
                   "User-Agent": opts.user_agent, "Origin": base, "Referer": base + "/chat"}
        headers.update(spec.headers)
        for attempt in (0, 1):
            opener = self._opener(spec, opts.user_agent, timeout, opts.proxy, force=bool(attempt))
            try:
                return _http.open_url(spec.chat_url, headers=headers, data=body, timeout=timeout, opener=opener)
            except _http.HTTPFailure as e:
                if attempt == 0 and e.status in (401, 403, 419):      # stale session: bootstrap again once
                    continue
                raise
        raise AssertionError("unreachable")  # pragma: no cover

    def _events(self, spec, model, resp) -> Iterator[str]:
        """Yield the ``delta`` chunks; if the server only sent whole ``message`` events, yield those."""
        got_delta, fallback = False, []
        for raw in _http.iter_lines(resp):
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
            if kind == "delta" and ev.get("chunk"):
                got_delta = True
                yield str(ev["chunk"])
            elif kind == "message" and ev.get("content"):
                fallback.append(str(ev["content"]))
            elif kind == "done":
                break
        if not got_delta and fallback:
            yield "\n\n".join(fallback)
