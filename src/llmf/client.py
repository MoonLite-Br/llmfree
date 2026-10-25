"""The Client: one unified entry point with automatic fallback."""

from __future__ import annotations

import functools
import logging
import threading
import time
import uuid
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from . import _cache, _http
from ._messages import Prompt, build_messages
from .discover import fetch_specs
from .errors import AllProvidersFailed, LLMFError, ModelNotFound, ProviderError
from .providers import ADAPTERS
from .providers.base import ModelSpec, Options, ProviderSpec
from .registry import Registry, Target
from ._types import (Attempt, ChatCompletion, ChatCompletionChunk, ChunkChoice, Delta, HealthResult,
                     ModelInfo, ProviderInfo, Reply)

log = logging.getLogger("llmf")

ModelArg = Union[None, str, Sequence[str]]


class _State:
    """Thread-safe cooldown / rate-limit / latency bookkeeping."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cool: Dict[Any, float] = {}
        self._last: Dict[str, float] = {}
        self._ewma: Dict[Target, float] = {}
        self._demoted = set()

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

    def ok(self, target: Target, latency: Optional[float] = None) -> None:
        with self._lock:
            self._cool.pop(target.provider, None)
            self._cool.pop(target, None)
            self._demoted.discard(target)
            if latency is not None:
                old = self._ewma.get(target)
                self._ewma[target] = latency if old is None else 0.7 * old + 0.3 * latency

    def seed(self, rows: List[Dict[str, Any]]) -> None:
        """Apply earlier ``doctor`` results: failures are demoted, latencies pre-load the EWMA."""
        with self._lock:
            for r in rows:
                try:
                    t = Target(str(r["provider"]), str(r["model"]))
                    if r.get("ok"):
                        self._ewma.setdefault(t, float(r.get("latency") or 2.0))
                        self._demoted.discard(t)
                    else:
                        self._demoted.add(t)
                except (KeyError, TypeError, ValueError):
                    continue

    def demote_unreliable(self, history: Dict[str, str]) -> None:
        """Models whose recent doctor success rate is low sink to the end of every plan."""
        with self._lock:
            for key, h in history.items():
                if _cache.unreliable(h) and "/" in key:
                    prov, model = key.split("/", 1)
                    self._demoted.add(Target(prov, model))

    def measured(self, max_latency: float) -> List[Target]:
        """Targets whose observed latency is <= ``max_latency`` (not demoted), fastest first."""
        with self._lock:
            rows = [(v, t) for t, v in self._ewma.items() if v <= max_latency and t not in self._demoted]
        return [t for _, t in sorted(rows)]

    def latency(self, target: Target) -> Optional[float]:
        with self._lock:
            return self._ewma.get(target)

    def order(self, targets: List[Target], intervals: Dict[str, float], adaptive: bool = False) -> List[Target]:
        ready, later = [], []
        for i, t in enumerate(targets):
            with self._lock:
                demoted = t in self._demoted
            bad = demoted or self.ready_in(t, intervals.get(t.provider, 0.0)) > 0
            (later if bad else ready).append((i, t))
        if adaptive:
            with self._lock:
                ready.sort(key=lambda p: (self._ewma.get(p[1], 2.0), p[0]))
        return [t for _, t in ready] + [t for _, t in later]


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


def _join(provider: Optional[str], model: ModelArg) -> ModelArg:
    """``provider="ovh", model="qwen"`` -> ``"ovh/qwen"`` (provider alone -> its default)."""
    if not provider:
        return model
    if model is not None and not isinstance(model, str):
        raise ValueError("provider= cannot be combined with a list of models")
    return "%s/%s" % (provider, model or "")


FAST_SECONDS = 1.0  # a measured model at or under this latency may join the dynamic "fast" tag
CHECK_PROMPT = "What is the capital of Vietnam? Answer in one short sentence."


class ChatStream:
    """Iterator of :class:`ChatCompletionChunk` (what ``create(stream=True)`` returns)."""

    def __init__(self, stream: Stream) -> None:
        self._stream = stream
        self._it = self._gen()

    def _gen(self) -> Iterator[ChatCompletionChunk]:
        cid, created = "chatcmpl-" + uuid.uuid4().hex[:24], int(time.time())
        it = iter(self._stream)
        first = next(it, None)  # fallback between providers happens here
        if first is None:
            raise AllProvidersFailed([], "empty stream")
        model = "%s/%s" % (self._stream.provider, self._stream.model)

        def chunk(delta: Delta, finish: Optional[str] = None) -> ChatCompletionChunk:
            return ChatCompletionChunk(cid, created, model, [ChunkChoice(0, delta, finish)])

        yield chunk(Delta(role="assistant", content=""))
        yield chunk(Delta(content=first))
        for piece in it:
            yield chunk(Delta(content=piece))
        yield chunk(Delta(), "stop")

    def __iter__(self) -> "ChatStream":
        return self

    def __next__(self) -> ChatCompletionChunk:
        return next(self._it)

    def __enter__(self) -> "ChatStream":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    @property
    def text(self) -> str:
        return self._stream.text

    @property
    def reply(self) -> Optional[Reply]:
        return self._stream.reply

    def collect(self) -> ChatCompletion:
        for _ in self:
            pass
        assert self._stream.reply is not None
        return ChatCompletion.from_reply(self._stream.reply)


class _Completions:
    """``llm.chat.completions.create(...)`` - the OpenAI-shaped entry point."""

    def __init__(self, client: "Client") -> None:
        self._c = client

    def create(self, *, messages: Sequence[dict], model: ModelArg = None, stream: bool = False,
               max_completion_tokens: Optional[int] = None, response_format: Optional[dict] = None,
               n: Optional[int] = None, **kw: Any):
        """Returns a :class:`ChatCompletion`, or a :class:`ChatStream` when ``stream=True``.

        Accepts the usual OpenAI parameters (``max_tokens``, ``temperature``, ``top_p``,
        ``stop``, ``tools``, ``response_format``) plus llmf's ``provider``, ``fallback``,
        ``proxy``, ``race`` and ``images``. Other keyword arguments go to the provider as-is.
        """
        if n not in (None, 1):
            raise ValueError("n > 1 is not supported")
        if kw.get("max_tokens") is None and max_completion_tokens is not None:
            kw["max_tokens"] = max_completion_tokens
        if isinstance(response_format, dict) and response_format.get("type") in ("json_object", "json_schema"):
            kw.setdefault("json", True)
        if stream:
            return ChatStream(self._c.stream(messages, model=model, **kw))
        return ChatCompletion.from_reply(self._c._chat_impl(messages, model=model, **kw))


class _Chat:
    """Callable shorthand (``llm.chat("hi")``) *and* namespace (``llm.chat.completions``)."""

    def __init__(self, client: "Client") -> None:
        self._c = client
        self.completions = _Completions(client)

    def __call__(self, prompt: Prompt, **kw: Any) -> Reply:
        return self._c._chat_impl(prompt, **kw)


class _Models:
    def __init__(self, client: "Client") -> None:
        self._c = client

    def __call__(self, live: bool = False) -> List[ModelInfo]:
        return self.list(live=live)

    def list(self, live: bool = False, include_non_chat: bool = False) -> List[ModelInfo]:
        """The model catalogue. ``live=True`` also asks each provider for the free *chat* ids it
        serves now (``include_non_chat=True`` keeps TTS / embedding / guard / image ids too)."""
        return self._c._models_impl(live, include_non_chat)

    def check(self, **kw: Any) -> List[HealthResult]:
        """Really call every model once and report which ones work (see ``llmf doctor``)."""
        return self._c._check_impl(**kw)

    def resolve(self, model: ModelArg) -> List[str]:
        """Which ``provider/model`` targets a name or alias expands to, in order."""
        return ["%s/%s" % t for t in self._c._reg.resolve(model)]


class _Providers:
    def __init__(self, client: "Client") -> None:
        self._c = client

    def __call__(self) -> List[ProviderInfo]:
        return self.list()

    def list(self) -> List[ProviderInfo]:
        return self._c._providers_impl()


class _Health:
    def __init__(self, client: "Client") -> None:
        self._c = client

    def __call__(self) -> List[HealthResult]:
        return self.check()

    def check(self) -> List[HealthResult]:
        """Quick ping of every provider's default model."""
        return self._c._health_impl()


class Client:
    """Configure once, call anywhere. All options have sensible defaults.

    Args:
        model: default model/alias for every call (``None`` = automatic chain).
        timeout: seconds per HTTP request.
        deadline: overall seconds budget for one call, across all fallbacks.
        max_attempts: hard cap on tries per call.
        retries: extra passes over the candidates for *transient* errors.
        max_tokens: default answer budget (reasoning models need >= 200).
        routing: ``"ranked"`` (fixed fallback order) or ``"adaptive"`` (fastest observed first).
        race: send each request to this many providers at once and keep the first answer
            (faster, but uses more of the free quotas). ``1`` = off.
        only / exclude: restrict the providers that may be used.
        builtin: load the built-in provider catalogue.
        transport: ``"urllib"`` (default), ``"auto"`` or ``"curl_cffi"`` (needs ``pip install curl_cffi``;
            browser-like TLS fingerprint). Process-wide. ``impersonate`` picks the browser profile (default ``chrome``).
        proxy: optional ``http://``, ``https://`` or ``socks4/4a/5/5h://`` proxy URL (your own).
        use_cache: read/write the ``llmf doctor`` health cache (``LLMF_NO_CACHE=1`` disables).
        vision_timeout: seconds per request when images are attached (image models are slow).
    """

    def __init__(self, *, model: ModelArg = None, timeout: float = 60.0, deadline: float = 180.0,
                 max_attempts: int = 8, retries: int = 1, max_tokens: int = 1024,
                 temperature: Optional[float] = None, only: Optional[Sequence[str]] = None,
                 exclude: Sequence[str] = (), builtin: bool = True,
                 user_agent: str = _http.DEFAULT_UA, proxy: Optional[str] = None,
                 transport: Optional[str] = None, impersonate: Optional[str] = None,
                 routing: str = "ranked", race: int = 1, use_cache: bool = True,
                 cache_dir: Optional[str] = None, vision_timeout: float = 90.0) -> None:
        self.model = model
        self.proxy = _http.check_proxy(proxy)
        if transport is not None or impersonate is not None:
            _http.configure_transport(transport, impersonate)   # process-wide
        self.timeout = timeout
        self.deadline = deadline
        self.max_attempts = max_attempts
        self.retries = retries
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.only = list(only) if only else None
        self.exclude = list(exclude)
        self.user_agent = user_agent
        self.routing = self._check_routing(routing)
        self.race = race
        self.use_cache = use_cache
        self.cache_dir = cache_dir
        self.vision_timeout = vision_timeout
        self._reg = Registry(builtin=builtin)
        self._state = _State()
        if use_cache:
            self._state.seed(_cache.load(self._cache_path()))
            self._state.demote_unreliable(_cache.load_history(self._cache_path()))
        # OpenAI-style namespaces; each is also directly callable (llm.chat("hi"), llm.models()).
        self.chat = _Chat(self)
        self.models = _Models(self)
        self.providers = _Providers(self)
        self.health = _Health(self)

    @staticmethod
    def _check_routing(routing: str) -> str:
        if routing not in ("ranked", "adaptive"):
            raise ValueError("routing must be 'ranked' or 'adaptive'")
        return routing

    def _cache_path(self) -> Optional[str]:
        return self.cache_dir or _cache.cache_dir()

    def configure(self, **kw: Any) -> "Client":
        """Change settings in place, e.g. ``configure(timeout=30, exclude=["blockrun"])``."""
        if "transport" in kw or "impersonate" in kw:
            _http.configure_transport(kw.pop("transport", None), kw.pop("impersonate", None))
        for k, v in kw.items():
            if k.startswith("_") or not hasattr(self, k) or callable(getattr(self, k)):
                raise TypeError("unknown setting %r" % k)
            if k == "proxy":
                v = _http.check_proxy(v)
            elif k == "routing":
                v = self._check_routing(v)
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
            specs = fetch_specs(self.timeout, self.user_agent, proxy=self.proxy)[:limit]
        except (_http.HTTPFailure, ValueError) as e:
            raise LLMFError("discovery failed: %s" % e) from None
        for s in specs:
            self._reg.add(s)
        return [s.name for s in specs]

    # --------------------------------------------------------------- introspect
    def _providers_impl(self) -> List[ProviderInfo]:
        return [ProviderInfo(s.name, s.chat_url, s.kind, s.default, [m.id for m in s.models],
                             s.min_interval, s.note) for s in self._reg.providers.values()]

    def _models_impl(self, live: bool = False, include_non_chat: bool = False) -> List[ModelInfo]:
        out = []
        hist = _cache.load_history(self._cache_path()) if self.use_cache else {}
        for t in self._reg.catalog():
            m = self._reg.model_spec(*t)
            h = hist.get("%s/%s" % (t.provider, t.model), "")
            out.append(ModelInfo(t.provider, t.model, tuple(self._reg.tags_of(t)),
                                 bool(m and m.vision), bool(m and m.verified and not m.broken),
                                 _cache.rate(h), len(h), bool(m.streams) if m else True))
        if live:
            known = {(i.provider, i.id) for i in out}
            for name, ids in self._live_ids(not include_non_chat).items():
                for mid in ids:
                    if (name, mid) not in known:
                        out.append(ModelInfo(name, mid, (), False, False))
        return out

    def _live_ids(self, chat_only: bool = True) -> Dict[str, List[str]]:
        from concurrent.futures import ThreadPoolExecutor

        specs = [s for s in self._reg.providers.values() if s.models_path]

        def one(s: ProviderSpec) -> List[str]:
            try:
                return ADAPTERS[s.kind].list_models(s, min(self.timeout, 20.0), self.user_agent, self.proxy,
                                                    chat_only)
            except LLMFError as e:
                log.debug("live models failed for %s: %s", s.name, e)
                return []

        with ThreadPoolExecutor(max_workers=max(1, len(specs))) as ex:
            return dict(zip([s.name for s in specs], ex.map(one, specs)))

    def _health_impl(self) -> List[HealthResult]:
        from concurrent.futures import ThreadPoolExecutor

        specs = list(self._reg.providers.values())
        msgs = build_messages("Reply with the single word: ok")

        def one(s: ProviderSpec) -> HealthResult:
            t0 = time.monotonic()
            opts = self._options(256, None, None, False, None, {})
            try:
                ADAPTERS[s.kind].complete(s, s.default, msgs, opts, min(self.timeout, 30.0))
                return HealthResult(s.name, s.default, True, time.monotonic() - t0)
            except LLMFError as e:
                return HealthResult(s.name, s.default, False, time.monotonic() - t0,
                                    getattr(e, "message", str(e)))

        with ThreadPoolExecutor(max_workers=max(1, len(specs))) as ex:
            return list(ex.map(one, specs))

    def _check_impl(self, *, providers: Optional[Sequence[str]] = None, include_live: bool = False,
                    include_limited: bool = False, include_non_chat: bool = False, timeout: float = 30.0,
                    vision_timeout: Optional[float] = None, prompt: str = CHECK_PROMPT,
                    on_result: Optional[Callable[[HealthResult], None]] = None,
                    save: bool = True) -> List[HealthResult]:
        """Call every catalogued model once (providers in parallel, models in sequence)."""
        from concurrent.futures import ThreadPoolExecutor

        reg = self._reg
        wanted = None
        if providers:
            wanted = {n for p in providers for n in reg._provider_names(p)}
            if not wanted:
                raise ModelNotFound("unknown provider(s): %s" % ", ".join(providers))
        targets = list(reg.catalog())
        if include_live:
            known = set(targets)
            for name, ids in self._live_ids(not include_non_chat).items():
                targets += [Target(name, i) for i in ids if Target(name, i) not in known]
        groups: Dict[str, List[Target]] = {}
        for t in targets:
            spec = reg.providers[t.provider]
            if (wanted is not None and t.provider not in wanted) or \
                    (not spec.checkable and not include_limited):
                continue
            groups.setdefault(t.provider, []).append(t)
        msgs = build_messages(prompt)
        opts = self._options(300, None, None, False, None, {})
        results: Dict[Target, HealthResult] = {}
        vtimeout = vision_timeout if vision_timeout is not None else max(timeout, 60.0)

        def work(name: str) -> None:
            spec = reg.providers[name]
            for t in groups[name]:
                if spec.min_interval > 0:
                    time.sleep(self._state.rate_wait(name, spec.min_interval))
                m = reg.model_spec(*t)
                t0 = time.monotonic()
                try:
                    comp = ADAPTERS[spec.kind].complete(spec, t.model, msgs, opts,
                                                        vtimeout if (m and m.vision) else timeout)
                    r = HealthResult(name, t.model, True, time.monotonic() - t0,
                                     answer=" ".join(comp.text.split())[:80], verified=bool(m and m.verified))
                except LLMFError as e:
                    r = HealthResult(name, t.model, False, time.monotonic() - t0,
                                     getattr(e, "message", str(e)), verified=bool(m and m.verified))
                results[t] = r
                if on_result:
                    on_result(r)

        if groups:
            with ThreadPoolExecutor(max_workers=len(groups)) as ex:
                list(ex.map(work, list(groups)))
        ordered = [results[t] for t in targets if t in results]
        rows = [{"provider": r.provider, "model": r.model, "ok": r.ok,
                 "latency": round(r.latency, 3), "error": r.error} for r in ordered]
        self._state.seed(rows)
        if save and self.use_cache and rows:
            merged = {(r["provider"], r["model"]): r for r in _cache.load(self._cache_path())}
            merged.update({(r["provider"], r["model"]): r for r in rows})
            _cache.save(self._cache_path(), list(merged.values()))
            _cache.record(self._cache_path(), [r for r in rows if r.get("error") != "skipped"])
        return ordered

    # ------------------------------------------------------------------ planning
    def _options(self, max_tokens, temperature, top_p, json_mode, tools, extra, stop=None):
        return Options(max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
                       temperature=temperature if temperature is not None else self.temperature,
                       top_p=top_p, stop=stop, json=json_mode, tools=tools, extra=extra,
                       user_agent=self.user_agent, proxy=self.proxy)

    def _plan(self, model: ModelArg, fallback: Optional[bool], vision: bool) -> List[Target]:
        reg = self._reg
        if model is None:
            model = self.model
        base = reg.tag("vision") if vision else reg.chain()
        targets = reg.resolve(model) if model is not None else list(base)
        is_fast = isinstance(model, str) and model.strip().lower() == "fast"
        if is_fast:  # "fast" follows measurements: add anything measured quick, sort by latency
            catalog = {t for t in reg.catalog() if not (reg.model_spec(*t) and reg.model_spec(*t).broken)}
            targets += [t for t in self._state.measured(FAST_SECONDS) if t in catalog and t not in targets]
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
        return self._state.order(plan, intervals, self.routing == "adaptive" or is_fast)

    def _sequence(self, plan: List[Target]) -> List[Target]:
        seq: List[Target] = []
        for _ in range(1 + max(0, self.retries)):
            seq.extend(plan)
        return seq[: self.max_attempts]

    def _prepare(self, prompt, system, images, model, fallback):
        messages = build_messages(prompt, system, images)
        return messages, self._plan(model, fallback, bool(images))

    # ----------------------------------------------------------------- core: chat
    def _attempt(self, t: Target, messages: List[dict], opts: Options, end: float,
                 errors: List[ProviderError], attempts: List[Attempt]):
        """One try. Returns ``(Reply, None)`` or ``(None, ProviderError)``."""
        spec = self._reg.providers[t.provider]
        self._throttle(spec, end - time.monotonic())
        t0 = time.monotonic()
        try:
            comp = ADAPTERS[spec.kind].complete(spec, t.model, messages, opts,
                                                max(1.0, min(opts.timeout or self.timeout, end - time.monotonic())))
        except ProviderError as e:
            log.debug("failed: %s", e)
            self._state.fail(e)
            errors.append(e)
            attempts.append(Attempt(t.provider, t.model, False, time.monotonic() - t0, str(e)))
            return None, e
        lat = time.monotonic() - t0
        self._state.ok(t, lat)
        attempts.append(Attempt(t.provider, t.model, True, lat))
        return Reply(comp.text, provider=t.provider, model=t.model, reasoning=comp.reasoning,
                     usage=comp.usage, finish_reason=comp.finish_reason,
                     tool_calls=comp.tool_calls, latency=lat, raw=comp.raw, attempts=attempts), None

    def _run_batch(self, batch: List[Target], messages, opts, end, errors, attempts):
        """Try ``batch`` concurrently; first success wins. Returns ``(reply, failures)``."""
        if len(batch) == 1:
            r, e = self._attempt(batch[0], messages, opts, end, errors, attempts)
            return r, ([(batch[0], e)] if e else [])
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        ex = ThreadPoolExecutor(max_workers=len(batch))
        futs = {ex.submit(self._attempt, t, messages, opts, end, errors, attempts): t for t in batch}
        pending, failures = set(futs), []
        try:
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for f in done:
                    r, e = f.result()
                    if r is not None:
                        return r, failures
                    failures.append((futs[f], e))
        finally:
            ex.shutdown(wait=False)  # losers finish in the background and are simply discarded
        return None, failures

    def _chat_impl(self, prompt: Prompt, *, model: ModelArg = None, provider: Optional[str] = None,
                   system: Optional[str] = None, images: Optional[Sequence[Any]] = None,
                   max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                   top_p: Optional[float] = None, json: bool = False,
                   tools: Optional[List[Any]] = None, fallback: Optional[bool] = None,
                   proxy: Optional[str] = None, race: Optional[int] = None, **extra: Any) -> Reply:
        """Ask a question; returns a :class:`Reply` (a ``str``)."""
        messages, plan = self._prepare(prompt, system, images, _join(provider, model), fallback)
        stop = extra.pop("stop", None)
        opts = self._options(max_tokens, temperature, top_p, json, tools, extra, stop)
        if proxy:
            opts.proxy = _http.check_proxy(proxy)
        if images:
            opts.timeout = max(self.timeout, self.vision_timeout)
        width = max(1, int(race if race is not None else self.race))
        errors: List[ProviderError] = []
        attempts: List[Attempt] = []
        dead = set()
        end = time.monotonic() + max(self.deadline, (opts.timeout or 0) * 1.5)
        seq = self._sequence(plan)
        pos, last_pass = 0, 0
        while pos < len(seq):
            batch: List[Target] = []
            while pos < len(seq) and len(batch) < width:
                t = seq[pos]
                pos += 1
                if t not in dead and t not in batch:
                    batch.append(t)
            if not batch:
                break
            left = end - time.monotonic()
            if left < 1.0:
                return self._fail(errors, "deadline of %.0fs reached" % self.deadline)
            pass_no = (pos - 1) // len(plan)
            if pass_no > last_pass:  # starting another pass over the candidates
                last_pass = pass_no
                time.sleep(min(1.0, left / 4))
            reply, failures = self._run_batch(batch, messages, opts, end, errors, attempts)
            if reply is not None:
                return reply
            for t, e in failures:
                if e is not None and not e.retryable:
                    dead.add(t)
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
    def stream(self, prompt: Prompt, *, model: ModelArg = None, provider: Optional[str] = None,
               system: Optional[str] = None, images: Optional[Sequence[Any]] = None,
               max_tokens: Optional[int] = None, temperature: Optional[float] = None,
               top_p: Optional[float] = None, json: bool = False, tools: Optional[List[Any]] = None,
               fallback: Optional[bool] = None, proxy: Optional[str] = None,
               race: Optional[int] = None, _on_done: Optional[Callable[[Reply], None]] = None,
               **extra: Any) -> Stream:
        """Like :meth:`chat` but yields text chunks as they arrive.

        Fallback happens only *before* the first chunk; after that a failure raises.
        (``race`` is accepted for symmetry but streaming always goes one provider at a time.)
        """
        messages, plan = self._prepare(prompt, system, images, _join(provider, model), fallback)
        stop = extra.pop("stop", None)
        opts = self._options(max_tokens, temperature, top_p, json, tools, extra, stop)
        if proxy:
            opts.proxy = _http.check_proxy(proxy)
        if images:
            opts.timeout = max(self.timeout, self.vision_timeout)

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
                                                min(opts.timeout or self.timeout, end - time.monotonic()))
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
                self._state.ok(t, time.monotonic() - t0)  # time-to-first-chunk
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
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, functools.partial(self._chat_impl, prompt, **kw))

    async def astream(self, prompt: Prompt, **kw: Any) -> AsyncIterator[str]:
        import asyncio

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
