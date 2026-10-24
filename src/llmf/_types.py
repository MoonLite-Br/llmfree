"""Public value types."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
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
    answer: Optional[str] = None
    verified: bool = True

    @property
    def name(self) -> str:
        return "%s/%s" % (self.provider, self.model)


# --------------------------------------------------------------------------
# OpenAI-shaped response objects (what ``llm.chat.completions.create`` returns)
# --------------------------------------------------------------------------

@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "Usage":
        d = d or {}
        p, c = int(d.get("prompt_tokens") or 0), int(d.get("completion_tokens") or 0)
        return cls(p, c, int(d.get("total_tokens") or (p + c)))


@dataclass
class Message:
    role: str = "assistant"
    content: str = ""
    reasoning: Optional[str] = None
    tool_calls: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.reasoning:
            d["reasoning"] = self.reasoning
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


@dataclass
class Choice:
    index: int
    message: Message
    finish_reason: Optional[str] = "stop"


@dataclass
class ChatCompletion:
    """Drop-in shape of OpenAI's ``chat.completion`` plus llmf routing info."""

    id: str
    created: int
    model: str  # "provider/model" that actually answered
    choices: List[Choice]
    usage: Usage
    provider: str = ""
    latency: float = 0.0
    attempts: List[Attempt] = field(default_factory=list)
    object: str = "chat.completion"

    @classmethod
    def from_reply(cls, reply: Reply) -> "ChatCompletion":
        msg = Message("assistant", reply.text, reply.reasoning, reply.tool_calls)
        return cls("chatcmpl-" + uuid.uuid4().hex[:24], int(time.time()), reply.source,
                   [Choice(0, msg, reply.finish_reason or "stop")], Usage.from_dict(reply.usage),
                   reply.provider, reply.latency, reply.attempts)

    @property
    def output_text(self) -> str:
        return self.choices[0].message.content

    def __str__(self) -> str:
        return self.output_text

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "object": self.object, "created": self.created, "model": self.model,
                "choices": [{"index": c.index, "message": c.message.to_dict(),
                             "finish_reason": c.finish_reason} for c in self.choices],
                "usage": {"prompt_tokens": self.usage.prompt_tokens,
                          "completion_tokens": self.usage.completion_tokens,
                          "total_tokens": self.usage.total_tokens}}


@dataclass
class Delta:
    role: Optional[str] = None
    content: Optional[str] = None


@dataclass
class ChunkChoice:
    index: int
    delta: Delta
    finish_reason: Optional[str] = None


@dataclass
class ChatCompletionChunk:
    id: str
    created: int
    model: str
    choices: List[ChunkChoice]
    object: str = "chat.completion.chunk"

    @property
    def text(self) -> str:
        return self.choices[0].delta.content or ""

    def to_dict(self) -> Dict[str, Any]:
        out = []
        for c in self.choices:
            d: Dict[str, Any] = {}
            if c.delta.role is not None:
                d["role"] = c.delta.role
            if c.delta.content is not None:
                d["content"] = c.delta.content
            out.append({"index": c.index, "delta": d, "finish_reason": c.finish_reason})
        return {"id": self.id, "object": self.object, "created": self.created,
                "model": self.model, "choices": out}
