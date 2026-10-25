"""Provider specs and the adapter interface."""

from __future__ import annotations

import contextlib
import json
import re
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
    streams: bool = True  # False: the endpoint answers in one piece even when asked to stream
    broken: bool = False  # known-dead: never picked automatically, still reachable as provider/model


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
    concurrency: int = 0  # max simultaneous requests (0 = the client's ``max_inflight``)
    aliases: Tuple[str, ...] = ()
    free_suffix: str = ""  # when listing live models, keep only ids with this suffix
    auto: bool = True  # False: only used when named explicitly, never in the automatic chain
    checkable: bool = True  # False for tightly quota-limited services: doctor skips them
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
    timeout: Optional[float] = None  # per-request override (e.g. longer for vision)


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
        inner = err.get("error")  # free.ai nests the text one level deeper
        msg = err.get("message") or (inner if isinstance(inner, str) else None) or msg
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
                    user_agent: str = _http.DEFAULT_UA, proxy: Optional[str] = None,
                    chat_only: bool = True) -> List[str]:
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
        return parse_model_list(payload, spec.free_suffix, chat_only)


_NON_CHAT_TYPES = {"image", "images", "audio", "video", "embedding", "embeddings", "speech", "tts", "stt",
                   "transcription", "moderation", "rerank", "reranker", "ocr", "image-generation",
                   "image_generation", "music", "3d"}
_NON_CHAT_ID = re.compile(
    r"(whisper|tts\b|\btts|embed|rerank|diffusion|stable-?diffusion|sdxl|flux|dall-?e|imagen|midjourney|"
    r"\bocr|ocr\b|voxtral|seedance|kling|sora|veo\b|\bwan\d|moderation|guard|safety|transcrib|speech|"
    r"text-to-|image-gen|-image\b|/image|music|\bbge-|\be5-|"
    r"realesrgan|\brmbg|demucs|deoldify|step1x|^sam$|madlad|upscal|inpaint|lance-)", re.I)
_CHAT_CATEGORIES = {"chat", "coding", "code", "reasoning", "vision", "text", "llm", "agent"}


def is_chat_model(mid: str, item: Any = None) -> bool:
    """Heuristic: is this live-listed entry a text chat model (not TTS/embedding/guard/image...)?"""
    if _NON_CHAT_ID.search(mid):
        return False
    if isinstance(item, dict):
        kind = str(item.get("type") or item.get("task") or item.get("category") or "").lower()
        if kind in _NON_CHAT_TYPES:
            return False
        arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        outs = item.get("output_modalities") or arch.get("output_modalities")
        if isinstance(outs, list) and outs and "text" not in [str(o).lower() for o in outs]:
            return False
        cats = item.get("categories")
        if isinstance(cats, list) and cats and not (_CHAT_CATEGORIES & {str(c).lower() for c in cats}):
            return False
    return True


def _is_free(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    if item.get("billing_mode", "free") != "free":
        return False
    if "self_hosted" in item and item["self_hosted"] is not True:   # free.ai: others are paid
        return False
    if item.get("premium") is True or item.get("paid") is True:
        return False
    if str(item.get("tier", "")).lower() in ("premium", "paid", "pro"):
        return False
    pricing = item.get("pricing")
    if isinstance(pricing, dict):
        for k in ("prompt", "completion", "input", "output"):
            try:
                if float(pricing.get(k) or 0) > 0:
                    return False
            except (TypeError, ValueError):
                continue
    return True


def parse_model_list(payload: Any, free_suffix: str = "", chat_only: bool = True) -> List[str]:
    """Ids of the *free* (and by default *chat*) models in a provider's ``/models`` payload."""
    items = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    ids: List[str] = []
    for it in items or []:
        mid = it if isinstance(it, str) else (it.get("id") or it.get("name")) if isinstance(it, dict) else None
        if not mid or not _is_free(it):
            continue
        if free_suffix and not str(mid).endswith(free_suffix):
            continue
        if chat_only and not is_chat_model(str(mid), it):
            continue
        ids.append(str(mid))
    return ids
