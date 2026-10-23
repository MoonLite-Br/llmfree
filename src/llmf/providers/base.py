"""Provider specs and the adapter interface."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import _http
from ..errors import ProviderError


@dataclass
class ModelSpec:
    id: str
    vision: bool = False
    verified: bool = True
    aliases: Tuple[str, ...] = ()
    note: str = ""


@dataclass
class ProviderSpec:
    name: str
    base_url: str
    chat_path: str = "/v1/chat/completions"
    models_path: Optional[str] = None
    kind: str = "openai"  # adapter key: "openai" | "chatjimmy"
    headers: Dict[str, str] = field(default_factory=dict)
    models: List[ModelSpec] = field(default_factory=list)
    default_model: Optional[str] = None
    min_interval: float = 0.0  # minimum seconds between requests
    aliases: Tuple[str, ...] = ()
    free_suffix: str = ""  # when listing live models, keep only ids with this suffix
    note: str = ""

    @property
    def chat_url(self) -> str:
        return self.base_url.rstrip("/") + self.chat_path

    @property
    def default(self) -> str:
        if self.default_model:
            return self.default_model
        return self.models[0].id if self.models else "default"


@dataclass
class Options:
    """Per-call generation options (already merged with client defaults)."""

    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[Any] = None
    json: bool = False
    tools: Optional[List[Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    user_agent: str = _http.DEFAULT_UA
    proxy: Optional[str] = None


@dataclass
class Completion:
    text: str
    reasoning: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[Any]] = None
    raw: Any = None


def error_from_body(body: str) -> Tuple[Optional[str], str]:
    """Extract ``(code, message)`` from the many error shapes seen in the wild."""
    try:
        obj = json.loads(body)
    except ValueError:
        return None, body.strip()[:300]
    if not isinstance(obj, dict):
        return None, body.strip()[:300]
    err = obj.get("error")
    code = obj.get("error_type") or obj.get("code")
    msg = obj.get("message")
    if isinstance(err, dict):
        code = err.get("code") or err.get("type") or code
        msg = err.get("message") or msg
    elif isinstance(err, str):
        msg = msg or err
    if "daily limit" in str(msg or "").lower():
        code = "daily_limit"
    debug = obj.get("debug")
    if debug and msg:
        msg = "%s (%s)" % (msg, debug)
    return (str(code) if code else None), str(msg or body.strip())[:300]


@contextlib.contextmanager
def translate(spec: ProviderSpec, model: str):
    """Turn transport / parsing exceptions into :class:`ProviderError`."""
    try:
        yield
    except ProviderError:
        raise
    except _http.HTTPFailure as e:
        code, msg = error_from_body(e.body) if e.status is not None else (None, e.body or e.kind)
        if e.status is not None and not msg:
            msg = "HTTP %s" % e.status
        raise ProviderError(
            spec.name, model, "%s%s" % ("HTTP %s: " % e.status if e.status else e.kind + ": ", msg),
            status=e.status, code=code,
        ) from None
    except _http.NETWORK_ERRORS as e:
        raise ProviderError(spec.name, model, "network: %s" % e) from None
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ProviderError(spec.name, model, "unparsable response: %r" % (e,)) from None


class Adapter:
    """Knows how to talk to one *kind* of endpoint."""

    def complete(self, spec: ProviderSpec, model: str, messages: List[dict],
                 opts: Options, timeout: float) -> Completion:  # pragma: no cover
        raise NotImplementedError

    def stream(self, spec: ProviderSpec, model: str, messages: List[dict],
               opts: Options, timeout: float) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError

    def list_models(self, spec: ProviderSpec, timeout: float,
                    user_agent: str = _http.DEFAULT_UA, proxy: Optional[str] = None) -> List[str]:
        """Live model ids (best effort). Default: OpenAI-style ``/models``."""
        if not spec.models_path:
            return []
        url = spec.base_url.rstrip("/") + spec.models_path
        headers = dict(spec.headers)
        headers.setdefault("User-Agent", user_agent)
        headers.setdefault("Accept", "application/json")
        with translate(spec, "(models)"):
            resp = _http.open_url(url, headers=headers, timeout=timeout, proxy=proxy)
            try:
                payload = json.loads(_http.decode_body(resp))
            finally:
                resp.close()
        return parse_model_list(payload, spec.free_suffix)


def parse_model_list(payload: Any, free_suffix: str = "") -> List[str]:
    items = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    ids: List[str] = []
    for it in items or []:
        if isinstance(it, str):
            mid, free = it, True
        elif isinstance(it, dict):
            mid = it.get("id") or it.get("name")
            free = it.get("billing_mode", "free") == "free"
        else:
            continue
        if not mid or not free:
            continue
        if free_suffix and not str(mid).endswith(free_suffix):
            continue
        ids.append(str(mid))
    return ids
