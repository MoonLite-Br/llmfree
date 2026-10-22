"""Public value types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Attempt:
    """One provider/model try (successful or not)."""

    provider: str
    model: str
    ok: bool
    latency: float = 0.0
    error: Optional[str] = None


class Reply(str):
    """The answer text, plus metadata.

    A ``Reply`` *is* a ``str`` – print it, slice it, ``json.loads`` it – and
    additionally carries ``provider``, ``model``, ``reasoning``, ``usage``,
    ``finish_reason``, ``tool_calls``, ``latency``, ``raw`` and ``attempts``.
    """

    provider: str
    model: str
    reasoning: Optional[str]
    usage: Optional[Dict[str, Any]]
    finish_reason: Optional[str]
    tool_calls: Optional[List[Any]]
    latency: float
    raw: Any
    attempts: List[Attempt]

    def __new__(
        cls,
        text: str = "",
        *,
        provider: str = "",
        model: str = "",
        reasoning: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        finish_reason: Optional[str] = None,
        tool_calls: Optional[List[Any]] = None,
        latency: float = 0.0,
        raw: Any = None,
        attempts: Optional[List[Attempt]] = None,
    ) -> "Reply":
        self = super().__new__(cls, text)
        self.provider = provider
        self.model = model
        self.reasoning = reasoning
        self.usage = usage
        self.finish_reason = finish_reason
        self.tool_calls = tool_calls
        self.latency = latency
        self.raw = raw
        self.attempts = attempts if attempts is not None else []
        return self

    @property
    def text(self) -> str:
        return str.__str__(self)

    @property
    def source(self) -> str:
        """``"provider/model"`` that produced this reply."""
        return "%s/%s" % (self.provider, self.model)

    def __getnewargs_ex__(self):  # keeps copy/pickle working for a str subclass
        meta = dict(
            provider=self.provider, model=self.model, reasoning=self.reasoning,
            usage=self.usage, finish_reason=self.finish_reason,
            tool_calls=self.tool_calls, latency=self.latency, raw=self.raw,
            attempts=self.attempts,
        )
        return (self.text,), meta


@dataclass
class ModelInfo:
    provider: str
    id: str
    tags: Tuple[str, ...] = ()
    vision: bool = False
    verified: bool = True

    @property
    def name(self) -> str:
        """Fully-qualified name usable as ``model=``."""
        return "%s/%s" % (self.provider, self.id)


@dataclass
class ProviderInfo:
    name: str
    base_url: str
    kind: str
    default_model: str
    models: List[str] = field(default_factory=list)
    min_interval: float = 0.0
    note: str = ""


@dataclass
class HealthResult:
    provider: str
    model: str
    ok: bool
    latency: float = 0.0
    error: Optional[str] = None
