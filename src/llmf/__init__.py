"""llmf (llmfree) - one simple call for free, keyless LLM endpoints.

    >>> import llmf
    >>> llmf.chat("Xin chào!")            # no key, no setup, automatic fallback
    >>> llmf.chat("Explain GIL", model="best")
    >>> for piece in llmf.stream("Count to 5"): print(piece, end="")
"""

from __future__ import annotations

import os
import threading
from typing import Any, List, Optional

from . import tools
from ._version import __version__
from .client import Client, Session, Stream
from .errors import AllProvidersFailed, LLMFError, ModelNotFound, ProviderError
from ._types import Attempt, HealthResult, ModelInfo, ProviderInfo, Reply

_lock = threading.Lock()
_default: Optional[Client] = None


def default_client() -> Client:
    """The shared client behind the module-level functions."""
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
            _default = Client(**kw)
        return _default


def chat(prompt, **kw: Any) -> Reply:
    return default_client().chat(prompt, **kw)


def stream(prompt, **kw: Any) -> Stream:
    return default_client().stream(prompt, **kw)


async def achat(prompt, **kw: Any) -> Reply:
    return await default_client().achat(prompt, **kw)


def astream(prompt, **kw: Any):
    return default_client().astream(prompt, **kw)


def session(system: Optional[str] = None, **defaults: Any) -> Session:
    return default_client().session(system, **defaults)


def models(live: bool = False) -> List[ModelInfo]:
    return default_client().models(live=live)


def providers() -> List[ProviderInfo]:
    return default_client().providers()


def health() -> List[HealthResult]:
    return default_client().health()


def register(*a: Any, **kw: Any):
    return default_client().register(*a, **kw)


def discover(**kw: Any) -> List[str]:
    return default_client().discover(**kw)


def configure(**kw: Any) -> Client:
    return default_client().configure(**kw)


__all__ = [
    "__version__", "Client", "Session", "Stream", "Reply", "chat", "stream", "achat", "astream",
    "session", "models", "providers", "health", "register", "discover", "configure",
    "default_client", "tools", "LLMFError", "ProviderError", "AllProvidersFailed", "ModelNotFound",
    "Attempt", "HealthResult", "ModelInfo", "ProviderInfo",
]
