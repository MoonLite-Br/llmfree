"""llmf (llmfree) - free, keyless LLMs behind one professional, OpenAI-shaped API.

    >>> from llmf import LLMF
    >>> llm = LLMF(proxy="socks5://127.0.0.1:1080", routing="adaptive")
    >>> r = llm.chat.completions.create(model="best",
    ...         messages=[{"role": "user", "content": "Xin chào"}])
    >>> r.choices[0].message.content      # or r.output_text

Shorthand, module level, zero setup:

    >>> import llmf
    >>> llmf.chat("Xin chào")             # a str with .provider / .model / .reasoning
"""

from __future__ import annotations

import os
import threading
from typing import Any, List, Optional

from . import tools
from ._types import (Attempt, ChatCompletion, ChatCompletionChunk, Choice, ChunkChoice, Delta,
                     HealthResult, Message, ModelInfo, ProviderInfo, Reply, Usage)
from ._version import __version__
from .client import ChatStream, Client, Session, Stream
from .errors import AllProvidersFailed, LLMFError, ModelNotFound, ProviderError

LLMF = Client  # the name to use in application code: ``llm = LLMF(...)``

_lock = threading.Lock()
_default: Optional[Client] = None


def default_client() -> Client:
    """The shared client behind the module-level helpers."""
    global _default
    with _lock:
        if _default is None:
            kw: dict = {}
            if os.environ.get("LLMF_TIMEOUT"):
                kw["timeout"] = float(os.environ["LLMF_TIMEOUT"])
            if os.environ.get("LLMF_PROXY"):
                kw["proxy"] = os.environ["LLMF_PROXY"]
            if os.environ.get("LLMF_MODEL"):
                kw["model"] = os.environ["LLMF_MODEL"]
            if os.environ.get("LLMF_ROUTING"):
                kw["routing"] = os.environ["LLMF_ROUTING"]
            _default = Client(**kw)
        return _default


class _Proxy:
    """Module-level mirror of ``default_client().<attr>`` (callable + attribute access)."""

    def __init__(self, attr: str) -> None:
        self._attr = attr

    def __call__(self, *a: Any, **kw: Any):
        return getattr(default_client(), self._attr)(*a, **kw)

    def __getattr__(self, name: str):
        return getattr(getattr(default_client(), self._attr), name)

    def __repr__(self) -> str:
        return "<llmf.%s>" % self._attr


chat = _Proxy("chat")            # llmf.chat("hi")  /  llmf.chat.completions.create(...)
models = _Proxy("models")        # llmf.models()    /  .list() .check() .resolve()
providers = _Proxy("providers")  # llmf.providers() /  .list()
health = _Proxy("health")        # llmf.health()    /  .check()


def stream(prompt, **kw: Any) -> Stream:
    return default_client().stream(prompt, **kw)


async def achat(prompt, **kw: Any) -> Reply:
    return await default_client().achat(prompt, **kw)


def astream(prompt, **kw: Any):
    return default_client().astream(prompt, **kw)


def session(system: Optional[str] = None, **defaults: Any) -> Session:
    return default_client().session(system, **defaults)


def register(*a: Any, **kw: Any):
    return default_client().register(*a, **kw)


def discover(**kw: Any) -> List[str]:
    return default_client().discover(**kw)


def configure(**kw: Any) -> Client:
    return default_client().configure(**kw)


__all__ = [
    "__version__", "LLMF", "Client", "Session", "Stream", "ChatStream", "Reply", "ChatCompletion",
    "ChatCompletionChunk", "Choice", "ChunkChoice", "Delta", "Message", "Usage", "chat", "stream",
    "achat", "astream", "session", "models", "providers", "health", "register", "discover",
    "configure", "default_client", "tools", "LLMFError", "ProviderError", "AllProvidersFailed",
    "ModelNotFound", "Attempt", "HealthResult", "ModelInfo", "ProviderInfo",
]
