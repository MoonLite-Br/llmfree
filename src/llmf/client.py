"""The Client: one unified entry point with automatic fallback."""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Sequence, Union

from . import _http
from ._messages import Prompt, build_messages
from .discover import fetch_specs
from .errors import AllProvidersFailed, LLMFError, ModelNotFound, ProviderError
from .providers import ADAPTERS
from .providers.base import ModelSpec, Options, ProviderSpec
from .registry import Registry, Target
from ._types import Attempt, HealthResult, ModelInfo, ProviderInfo, Reply

log = logging.getLogger("llmf")

ModelArg = Union[None, str, Sequence[str]]


class _State:
    """Thread-safe cooldown / rate-limit bookkeeping."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cool: Dict[Any, float] = {}
        self._last: Dict[str, float] = {}

    def ready_in(self, target: Target, min_interval: float) -> float:
        now = time.monotonic()
        with self._lock:
            wait = max(self._cool.get(target.provider, 0.0), self._cool.get(target, 0.0)) - now
            wait = max(wait, self._last.get(target.provider, -1e9) + min_interval - now)
        return max(0.0, wait)

    def rate_wait(self, provider: str, min_interval: float) -> float:
        """Reserve a request slot; return seconds to sleep before using it."""
        now = time.monotonic()
        with self._lock:
            slot = max(now, self._last.get(provider, -1e9) + min_interval)
            self._last[provider] = slot
        return slot - now

    def fail(self, err: ProviderError) -> None:
        key: Any = err.provider if err.scope == "provider" else Target(err.provider, err.model)
        with self._lock:
            self._cool[key] = time.monotonic() + err.cooldown

    def ok(self, target: Target) -> None:
        with self._lock:
            self._cool.pop(target.provider, None)
            self._cool.pop(target, None)

    def order(self, targets: List[Target], intervals: Dict[str, float]) -> List[Target]:
        ready = [t for t in targets if self.ready_in(t, intervals.get(t.provider, 0.0)) <= 0]
        later = [t for t in targets if t not in ready]
        return ready + later


class Stream:
    """Iterator of text chunks. After exhaustion, ``.reply`` holds the full answer."""

    def __init__(self, gen: Callable[["Stream"], Iterator[str]],
                 on_done: Optional[Callable[[Reply], None]] = None) -> None:
        self.provider = ""
        self.model = ""
        self.reply: Optional[Reply] = None
        self._parts: List[str] = []
        self._on_done = on_done
        self._it = gen(self)

    def __iter__(self) -> "Stream":
        return self

    def __next__(self) -> str:
        try:
            chunk = next(self._it)
        except StopIteration:
            if self.reply is not None and self._on_done:
                cb, self._on_done = self._on_done, None
                cb(self.reply)
            raise
        self._parts.append(chunk)
        return chunk

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def collect(self) -> Reply:
        for _ in self:
            pass
        assert self.reply is not None
        return self.reply


class Client:
    """Configure once, call anywhere. All options have sensible defaults.

    Args:
        model: default model/alias for every call (``None`` = automatic chain).
        timeout: seconds per HTTP request.
        deadline: overall seconds budget for one call, across all fallbacks.
        max_attempts: hard cap on tries per call.
        retries: extra passes over the candidates for *transient* errors.
        max_tokens: default answer budget (reasoning models need >= 200).
        only / exclude: restrict the providers that may be used.
        builtin: load the built-in provider catalogue.
    """

    def __init__(self, *, model: ModelArg = None, timeout: float = 60.0, deadline: float = 180.0,
                 max_attempts: int = 8, retries: int = 1, max_tokens: int = 1024,
                 temperature: Optional[float] = None, only: Optional[Sequence[str]] = None,
                 exclude: Sequence[str] = (), builtin: bool = True,
                 user_agent: str = _http.DEFAULT_UA) -> None:
        self.model = model
        self.timeout = timeout
        self.deadline = deadline
        self.max_attempts = max_attempts
        self.retries = retries
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.only = list(only) if only else None
        self.exclude = list(exclude)
        self.user_agent = user_agent
        self._reg = Registry(builtin=builtin)
        self._state = _State()

    def configure(self, **kw: Any) -> "Client":
        """Change settings in place, e.g. ``configure(timeout=30, exclude=["blockrun"])``."""
        for k, v in kw.items():
            if k.startswith("_") or not hasattr(self, k) or callable(getattr(self, k)):
                raise TypeError("unknown setting %r" % k)
            setattr(self, k, list(v) if k in ("only", "exclude") and v else v)
        return self

    # ------------------------------------------------------------ registration
    def register(self, name: str, base_url: str, models: Union[str, Sequence[str]],
                 *, headers: Optional[Dict[str, str]] = None, chat_path: str = "/chat/completions",
                 kind: str = "openai", vision: bool = False, min_interval: float = 0.0,
                 front: bool = False, note: str = "custom") -> ProviderSpec:
        """Add your own endpoint. ``base_url`` usually ends in ``/v1``."""
        if kind not in ADAPTERS:
            raise ValueError("kind must be one of %s" % sorted(ADAPTERS))
        ids = [models] if isinstance(models, str) else list(models)
        if not ids:
            raise ValueError("models must not be empty")
        if base_url.rstrip("/").endswith("/chat/completions"):
            chat_path = ""
        spec = ProviderSpec(name=name, base_url=base_url, chat_path=chat_path, kind=kind,
                            headers=dict(headers or {}), min_interval=min_interval, note=note,
                            models=[ModelSpec(i, vision=vision, verified=False) for i in ids],
                            default_model=ids[0])
        self._reg.add(spec, front=front)
        if vision:
            self._reg.tag_add("vision", Target(name, spec.default))
        return spec

    def discover(self, *, limit: int = 5) -> List[str]:
        """Pull live keyless endpoints from the stillworks API and register them."""
        try:
            specs = fetch_specs(self.timeout, self.user_agent)[:limit]
        except (_http.HTTPFailure, ValueError) as e:
            raise LLMFError("discovery failed: %s" % e) from None
        for s in specs:
            self._reg.add(s)
        return [s.name for s in specs]

    # --------------------------------------------------------------- introspect
    def providers(self) -> List[ProviderInfo]:
        return [ProviderInfo(s.name, s.chat_url, s.kind, s.default, [m.id for m in s.models],
                             s.min_interval, s.note) for s in self._reg.providers.values()]

    def models(self, live: bool = False) -> List[ModelInfo]:
        """The model catalogue. ``live=True`` also asks each provider for new free models."""
        out = []
        for t in self._reg.catalog():
            m = self._reg.model_spec(*t)
            out.append(ModelInfo(t.provider, t.model, tuple(self._reg.tags_of(t)),
                                 bool(m and m.vision), bool(m and m.verified)))
        if live:
            known = {(i.provider, i.id) for i in out}
            for name, ids in self._live_ids().items():
                for mid in ids:
                    if (name, mid) not in known:
                        out.append(ModelInfo(name, mid, (), False, False))
        return out

    def _live_ids(self) -> Dict[str, List[str]]:
        specs = [s for s in self._reg.providers.values() if s.models_path]

        def one(s: ProviderSpec) -> List[str]:
            try:
                return ADAPTERS[s.kind].list_models(s, min(self.timeout, 20.0), self.user_agent)
            except LLMFError as e:
                log.debug("live models failed for %s: %s", s.name, e)
                return []

        with ThreadPoolExecutor(max_workers=max(1, len(specs))) as ex:
            return dict(zip([s.name for s in specs], ex.map(one, specs)))

    def health(self) -> List[HealthResult]:
        """Ping every provider's default model once (in parallel)."""
        specs = list(self._reg.providers.values())
        msgs = build_messages("Reply with the single word: ok")

        def one(s: ProviderSpec) -> HealthResult:
            t0 = time.monotonic()
            opts = self._options(256, None, None, False, None, {})
            try:
                ADAPTERS[s.kind].complete(s, s.default, msgs, opts, min(self.timeout, 30.0))
                return HealthResult(s.name, s.default, True, time.monotonic() - t0)
            except LLMFError as e:
                return HealthResult(s.name, s.default, False, time.monotonic() - t0, str(e))

        with ThreadPoolExecutor(max_workers=max(1, len(specs))) as ex:
            return list(ex.map(one, specs))

    # ------------------------------------------------------------------ planning
    def _options(self, max_tokens, temperature, top_p, json_mode, tools, extra, stop=None):
        return Options(max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
                       temperature=temperature if temperature is not None else self.temperature,
                       top_p=top_p, stop=stop, json=json_mode, tools=tools, extra=extra,
                       user_agent=self.user_agent)

    def _plan(self, model: ModelArg, fallback: Optional[bool], vision: bool) -> List[Target]:
        reg = self._reg
        if model is None:
            model = self.model
        base = reg.tag("vision") if vision else reg.chain()
        targets = reg.resolve(model) if model is not None else list(base)
        if fallback is None:
            fallback = model is None
        if fallback:
            targets += base
        seen, plan = set(), []
        for t in targets:
            ok = (self.only is None or t.provider in self.only) and t.provider not in self.exclude
            if ok and t not in seen:
                seen.add(t)
                plan.append(t)
        if not plan:
            raise ModelNotFound("no usable provider after only=/exclude= filtering")
        intervals = {n: s.min_interval for n, s in reg.providers.items()}
        return self._state.order(plan, intervals)

    def _sequence(self, plan: List[Target]) -> List[Target]:
        seq: List[Target] = []
        for _ in range(1 + max(0, self.retries)):
            seq.extend(plan)
        return seq[: self.max_attempts]

    def _prepare(self, prompt, system, images, model, fallback):
        messages = build_messages(prompt, system, images)
        return messages, self._plan(model, fallback, bool(images))

    # ----------------------------------------------------------------- core: chat
    def chat(self, prompt: Prompt, *, model: ModelArg = None, system: Optional[str] = None,
             images: Optional[Sequence[Any]] = None, max_tokens: Optional[int] = None,
             temperature: Optional[float] = None, top_p: Optional[float] = None,
             json: bool = False, tools: Optional[List[Any]] = None, fallback: Optional[bool] = None,
             **extra: Any) -> Reply:
        """Ask a question; returns a :class:`Reply` (a ``str``)."""
        messages, plan = self._prepare(prompt, system, images, model, fallback)
        stop = extra.pop("stop", None)
        opts = self._options(max_tokens, temperature, top_p, json, tools, extra, stop)
        errors: List[ProviderError] = []
        attempts: List[Attempt] = []
        dead = set()
        end = time.monotonic() + self.deadline
        seq = self._sequence(plan)
        for i, t in enumerate(seq):
            if t in dead:
                continue
            left = end - time.monotonic()
            if left < 1.0:
                return self._fail(errors, "deadline of %.0fs reached" % self.deadline)
            if i and i % len(plan) == 0:
                time.sleep(min(1.0, left / 4))
            spec = self._reg.providers[t.provider]
            self._throttle(spec, left)
            t0 = time.monotonic()
            try:
                comp = ADAPTERS[spec.kind].complete(spec, t.model, messages, opts,
                                                    min(self.timeout, end - time.monotonic()))
            except ProviderError as e:
                log.debug("failed: %s", e)
                self._state.fail(e)
                errors.append(e)
                attempts.append(Attempt(t.provider, t.model, False, time.monotonic() - t0, str(e)))
                if not e.retryable:
                    dead.add(t)
                continue
            self._state.ok(t)
            lat = time.monotonic() - t0
            attempts.append(Attempt(t.provider, t.model, True, lat))
            return Reply(comp.text, provider=t.provider, model=t.model, reasoning=comp.reasoning,
                         usage=comp.usage, finish_reason=comp.finish_reason,
                         tool_calls=comp.tool_calls, latency=lat, raw=comp.raw, attempts=attempts)
        return self._fail(errors, "")

    def _throttle(self, spec: ProviderSpec, budget: float) -> None:
        if spec.min_interval > 0:
            wait = self._state.rate_wait(spec.name, spec.min_interval)
            if wait > 0:
                time.sleep(min(wait, max(0.0, budget - 1.0)))

    @staticmethod
    def _fail(errors: List[ProviderError], note: str):
        raise AllProvidersFailed(errors, note)

    # --------------------------------------------------------------- core: stream
    def stream(self, prompt: Prompt, *, model: ModelArg = None, system: Optional[str] = None,
               images: Optional[Sequence[Any]] = None, max_tokens: Optional[int] = None,
               temperature: Optional[float] = None, top_p: Optional[float] = None,
               json: bool = False, tools: Optional[List[Any]] = None,
               fallback: Optional[bool] = None, _on_done: Optional[Callable[[Reply], None]] = None,
               **extra: Any) -> Stream:
        """Like :meth:`chat` but yields text chunks as they arrive.

        Fallback happens only *before* the first chunk; after that a failure raises.
        """
        messages, plan = self._prepare(prompt, system, images, model, fallback)
        stop = extra.pop("stop", None)
        opts = self._options(max_tokens, temperature, top_p, json, tools, extra, stop)

        def gen(st: Stream) -> Iterator[str]:
            errors: List[ProviderError] = []
            attempts: List[Attempt] = []
            dead = set()
            end = time.monotonic() + self.deadline
            seq = self._sequence(plan)
            for i, t in enumerate(seq):
                if t in dead:
                    continue
                left = end - time.monotonic()
                if left < 1.0:
                    self._fail(errors, "deadline of %.0fs reached" % self.deadline)
                if i and i % len(plan) == 0:
                    time.sleep(min(1.0, left / 4))
                spec = self._reg.providers[t.provider]
                self._throttle(spec, left)
                t0 = time.monotonic()
                it = ADAPTERS[spec.kind].stream(spec, t.model, messages, opts,
                                                min(self.timeout, end - time.monotonic()))
                try:
                    first = next(it)
                except StopIteration:
                    first = None
                    e: Optional[ProviderError] = ProviderError(t.provider, t.model, "empty stream",
                                                                status=200, code="empty")
                except ProviderError as pe:
                    first, e = None, pe
                else:
                    e = None
                if e is not None:
                    self._state.fail(e)
                    errors.append(e)
                    attempts.append(Attempt(t.provider, t.model, False, time.monotonic() - t0, str(e)))
                    if not e.retryable:
                        dead.add(t)
                    continue
                st.provider, st.model = t.provider, t.model
                self._state.ok(t)
                yield first
                try:
                    for chunk in it:
                        yield chunk
                except ProviderError as pe:
                    self._state.fail(pe)
                    raise
                lat = time.monotonic() - t0
                attempts.append(Attempt(t.provider, t.model, True, lat))
                st.reply = Reply("".join(st._parts).strip(), provider=t.provider, model=t.model,
                                 latency=lat, attempts=attempts)
                return
            self._fail(errors, "")

        return Stream(gen, _on_done)

    # ---------------------------------------------------------------------- async
    async def achat(self, prompt: Prompt, **kw: Any) -> Reply:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, functools.partial(self.chat, prompt, **kw))

    async def astream(self, prompt: Prompt, **kw: Any) -> AsyncIterator[str]:
        loop = asyncio.get_event_loop()
        it = iter(await loop.run_in_executor(None, functools.partial(self.stream, prompt, **kw)))
        done = object()
        while True:
            chunk = await loop.run_in_executor(None, next, it, done)
            if chunk is done:
                return
            yield chunk  # type: ignore[misc]

    def session(self, system: Optional[str] = None, **defaults: Any) -> "Session":
        return Session(self, system=system, **defaults)


class Session:
    """Multi-turn conversation that remembers history.

    >>> s = llmf.Session(system="Be brief.")
    >>> s("My name is An")
    >>> s("What is my name?")
    """

    def __init__(self, client: Client, system: Optional[str] = None, **defaults: Any) -> None:
        self._client = client
        self.system = system
        self.defaults = defaults
        self.history: List[dict] = []

    def reset(self) -> None:
        self.history.clear()

    def _msgs(self, prompt: str) -> List[dict]:
        return self.history + [{"role": "user", "content": prompt}]

    def __call__(self, prompt: str, **kw: Any) -> Reply:
        opts = {**self.defaults, **kw}
        opts.setdefault("system", self.system)
        reply = self._client.chat(self._msgs(prompt), **opts)
        self.history += [{"role": "user", "content": prompt},
                         {"role": "assistant", "content": reply.text}]
        return reply

    def stream(self, prompt: str, **kw: Any) -> Stream:
        opts = {**self.defaults, **kw}
        opts.setdefault("system", self.system)

        def done(reply: Reply) -> None:
            self.history += [{"role": "user", "content": prompt},
                             {"role": "assistant", "content": reply.text}]

        return self._client.stream(self._msgs(prompt), _on_done=done, **opts)
