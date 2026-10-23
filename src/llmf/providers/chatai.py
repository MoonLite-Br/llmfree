"""Adapter for chatai.org (CSRF + session cookie, then an SSE chat endpoint).

The free tier is limited to a few requests per IP per day. llmf respects that:
on the daily-limit 429 the provider is put to sleep for hours instead of retried.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import threading
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

from .. import _http
from ..errors import ProviderError
from .base import Completion, ProviderSpec, translate
from .openai_compat import OpenAIAdapter

SESSION_TTL = 7000.0  # the site's session lives ~2h
_META = re.compile(r"""<meta[^>]+name=["']csrf-token["'][^>]*content=["']([^"']+)["']""", re.I)
_META_REV = re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]*name=["']csrf-token["']""", re.I)


class _Session:
    def __init__(self, opener: urllib.request.OpenerDirector, csrf: str) -> None:
        self.opener, self.csrf, self.born = opener, csrf, time.monotonic()

    @property
    def fresh(self) -> bool:
        return time.monotonic() - self.born < SESSION_TTL


class ChatAIAdapter(OpenAIAdapter):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[Tuple[Optional[str], str], _Session] = {}

    # ---------------------------------------------------------------- session
    def _session(self, spec: ProviderSpec, ua: str, timeout: float, proxy: Optional[str],
                 force: bool = False) -> _Session:
        key = (proxy, spec.base_url)
        with self._lock:
            sess = self._sessions.get(key)
            if sess and sess.fresh and not force:
                return sess
        jar = http.cookiejar.CookieJar()
        opener = _http.build_opener(proxy, urllib.request.HTTPCookieProcessor(jar))
        page = spec.base_url.rstrip("/") + "/chat"
        resp = _http.open_url(page, headers={"User-Agent": ua, "Accept": "text/html"},
                              timeout=timeout, opener=opener)
        try:
            html = _http.decode_body(resp)
        finally:
            resp.close()
        m = _META.search(html) or _META_REV.search(html)
        if not m:
            raise ValueError("csrf-token meta tag not found (site layout changed?)")
        sess = _Session(opener, m.group(1))
        with self._lock:
            self._sessions[key] = sess
        return sess

    def _request(self, spec, model, messages, opts, stream):
        # This endpoint takes just model + messages; it always answers with SSE.
        body = {"model": model, "messages": messages}
        base = spec.base_url.rstrip("/")
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
                   "User-Agent": opts.user_agent, "Origin": base, "Referer": base + "/chat"}
        headers.update(spec.headers)
        return spec.chat_url, headers, json.dumps(body).encode("utf-8")

    def _open(self, spec, url, headers, data, timeout, opts):
        for attempt in (0, 1):
            sess = self._session(spec, opts.user_agent, timeout, opts.proxy, force=bool(attempt))
            h = dict(headers)
            h["X-CSRF-Token"] = sess.csrf
            try:
                return _http.open_url(url, headers=h, data=data, timeout=timeout, opener=sess.opener)
            except _http.HTTPFailure as e:
                if attempt == 0 and e.status in (401, 403, 419):  # stale session -> refresh once
                    continue
                raise
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------ calls
    def complete(self, spec, model, messages, opts, timeout) -> Completion:
        text = "".join(self.stream(spec, model, messages, opts, timeout)).strip()
        if not text:
            raise ProviderError(spec.name, model, "empty answer", status=200, code="empty")
        return Completion(text=text, finish_reason="stop")

    def list_models(self, spec, timeout, user_agent=_http.DEFAULT_UA, proxy=None) -> List[str]:
        return []  # no public model listing


