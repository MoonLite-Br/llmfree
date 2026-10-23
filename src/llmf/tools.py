"""Optional single-purpose tools (not general chat providers).

``ask_langchain_docs`` talks to the public "Chat LangChain" docs agent. It only
answers LangChain / LangGraph / LangSmith / Deep Agents questions and refuses
everything else, so it is deliberately *not* part of the ``llmf.chat`` chain.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

from . import _http
from ._types import Reply
from .errors import ProviderError

LANGCHAIN_BACKEND = ("https://chat-langchain-external-707c6e45e5075e168a6835a7d23a9934"
                     ".us.langgraph.app")
_TOKEN_TTL = 23 * 3600.0
_lock = threading.Lock()
_tokens: Dict[Any, Any] = {}  # (backend, proxy) -> (token, born)

NAME = "langchain-docs"


class DocsReply(Reply):
    """A :class:`Reply` that also says whether the agent refused as off-topic."""

    off_topic: bool = False


def _call(url: str, token: Optional[str], payload: Optional[dict], timeout: float,
          proxy: Optional[str], ua: str) -> Any:
    headers = {"User-Agent": ua, "Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload if payload is not None else {}).encode()
    try:
        resp = _http.open_url(url, headers=headers, data=data, timeout=timeout, proxy=proxy)
        try:
            return json.loads(_http.decode_body(resp))
        finally:
            resp.close()
    except _http.HTTPFailure as e:
        raise ProviderError(NAME, "docs-agent", "HTTP %s: %s" % (e.status or e.kind, e.body[:200]),
                            status=e.status) from None
    except ValueError as e:
        raise ProviderError(NAME, "docs-agent", "unparsable response: %r" % (e,)) from None


def _guest_token(backend: str, timeout: float, proxy: Optional[str], ua: str, force=False) -> str:
    key = (backend, proxy)
    with _lock:
        hit = _tokens.get(key)
        if hit and not force and time.monotonic() - hit[1] < _TOKEN_TTL:
            return hit[0]
    obj = _call(backend + "/identity/guest", None, None, timeout, proxy, ua)
    token = obj.get("token") if isinstance(obj, dict) else None
    if not token:
        raise ProviderError(NAME, "docs-agent", "no guest token (backend may have moved)")
    with _lock:
        _tokens[key] = (token, time.monotonic())
    return token


def _final_text(obj: dict) -> str:
    ai = [m for m in obj.get("messages", []) if isinstance(m, dict) and m.get("type") == "ai"]
    if not ai:
        return ""
    content = ai[-1].get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict)
                       and p.get("type") == "text").strip()
    return ""


def ask_langchain_docs(question: str, *, backend: str = LANGCHAIN_BACKEND, timeout: float = 60.0,
                       proxy: Optional[str] = None, user_agent: str = _http.DEFAULT_UA) -> DocsReply:
    """Ask the LangChain docs agent. Returns a :class:`DocsReply` (``.off_topic`` flag).

    Limits: ~10 requests/minute/IP and 5-15 s latency. The backend URL can change
    when LangChain redeploys - pass ``backend=`` if so.
    """
    backend = backend.rstrip("/")
    _http.check_proxy(proxy)
    t0 = time.monotonic()
    for attempt in (0, 1):
        token = _guest_token(backend, timeout, proxy, user_agent, force=bool(attempt))
        try:
            thread = _call(backend + "/threads", token, {}, timeout, proxy, user_agent)
            tid = thread.get("thread_id")
            if not tid:
                raise ProviderError(NAME, "docs-agent", "no thread_id in response")
            body = {"assistant_id": "docs-agent",
                    "input": {"messages": [{"role": "user", "content": question}]}}
            obj = _call("%s/threads/%s/runs/wait" % (backend, tid), token, body, timeout,
                        proxy, user_agent)
            break
        except ProviderError as e:
            if attempt == 0 and e.status in (401, 403):  # expired guest token -> refresh once
                continue
            raise
    text = _final_text(obj) if isinstance(obj, dict) else ""
    if not text:
        raise ProviderError(NAME, "docs-agent", "empty answer", status=200, code="empty")
    usage = None
    for m in reversed(obj.get("messages", [])):
        if isinstance(m, dict) and m.get("usage_metadata"):
            usage = m["usage_metadata"]
            break
    reply = DocsReply(text, provider=NAME, model="docs-agent", usage=usage,
                      latency=time.monotonic() - t0, raw=obj)
    reply.off_topic = bool(obj.get("off_topic_query", False))
    return reply
