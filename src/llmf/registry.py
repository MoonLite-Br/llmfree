"""Provider registry and model-name resolution."""

from __future__ import annotations

import difflib
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Union

from .errors import ModelNotFound
from .providers.base import ModelSpec, ProviderSpec
from .providers.builtin import BUILTIN, TAGS


class Target(NamedTuple):
    provider: str
    model: str


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _tail(model_id: str) -> str:
    return _norm(model_id.rsplit("/", 1)[-1].replace(":free", ""))


class Registry:
    def __init__(self, builtin: bool = True) -> None:
        self.providers: Dict[str, ProviderSpec] = {}
        self._tags: Dict[str, List[Target]] = {}
        self._extra_chain: List[Target] = []
        self._front_chain: List[Target] = []
        if builtin:
            for spec in BUILTIN:
                self.add(spec, chain=False)
            self._tags = {k: [Target(*t) for t in v] for k, v in TAGS.items()}

    # ------------------------------------------------------------------ mutate
    def add(self, spec: ProviderSpec, *, front: bool = False, chain: bool = True) -> None:
        self.providers[spec.name] = spec
        if chain:
            t = Target(spec.name, spec.default)
            (self._front_chain if front else self._extra_chain).append(t)

    # ------------------------------------------------------------------ lookup
    def chain(self) -> List[Target]:
        """Default fallback chain: custom-front, builtin defaults in rank order, custom."""
        builtin_names = {s.name for s in BUILTIN}
        core = [Target(n, s.default) for n, s in self.providers.items() if n in builtin_names and s.auto]
        return _dedupe(self._front_chain + core + self._extra_chain)

    def tag(self, name: str) -> List[Target]:
        out = []
        for t in self._tags.get(name, []):
            m = self.model_spec(*t)
            if t.provider in self.providers and not (m and m.broken):
                out.append(t)
        return out

    def tag_add(self, name: str, target: Target) -> None:
        self._tags.setdefault(name, []).append(target)

    def tag_names(self) -> List[str]:
        return list(self._tags)

    def catalog(self) -> List[Target]:
        return [Target(n, m.id) for n, s in self.providers.items() for m in s.models]

    def model_spec(self, provider: str, model: str) -> Optional[ModelSpec]:
        spec = self.providers.get(provider)
        if spec:
            for m in spec.models:
                if m.id == model:
                    return m
        return None

    def tags_of(self, target: Target) -> List[str]:
        return [k for k, v in self._tags.items() if target in v]

    def _provider_names(self, head: str) -> List[str]:
        h = head.strip().lower()
        if h in self.providers:
            return [h]
        found = [n for n, s in self.providers.items() if h in s.aliases]
        return found

    # ----------------------------------------------------------------- resolve
    def resolve(self, model: Union[None, str, Sequence[str]]) -> List[Target]:
        """Map a user-facing ``model`` value to an ordered list of targets."""
        if model is None:
            return self.chain()
        if not isinstance(model, str):
            out: List[Target] = []
            for m in model:
                out.extend(self.resolve(m))
            return _dedupe(out)
        q = model.strip()
        low = q.lower()
        if low in ("", "auto", "default"):
            return self.chain()
        if low in self._tags:
            return self.tag(low)
        head, sep, rest = q.partition("/")
        names = self._provider_names(head)
        if names:
            return self._in_providers(names, rest.strip() if sep else "")
        hits = self._fuzzy(q)
        if hits:
            return hits
        raise ModelNotFound(self._not_found(q))

    def _in_providers(self, names: List[str], rest: str) -> List[Target]:
        out: List[Target] = []
        for n in names:
            spec = self.providers[n]
            if not rest or rest.lower() in ("auto", "default"):
                out.append(Target(n, spec.default))
                continue
            hits = self._fuzzy(rest, only=n)
            out.extend(hits if hits else [Target(n, rest)])  # pass unknown ids through
        return out

    def _fuzzy(self, q: str, only: Optional[str] = None) -> List[Target]:
        nq = _norm(q)
        if not nq:
            return []
        exact: List[Target] = []
        partial: List[Target] = []
        for n, s in self.providers.items():
            if only and n != only:
                continue
            for m in s.models:
                if m.broken:
                    continue
                names = [m.id] + list(m.aliases)
                keys = {_norm(x) for x in names} | {_tail(x) for x in names}
                if nq in keys:
                    exact.append(Target(n, m.id))
                elif any(nq in k for k in keys):
                    partial.append(Target(n, m.id))
        return exact + partial  # exact matches first, then looser ones as extra fallbacks

    def _not_found(self, q: str) -> str:
        ids = [m.id for s in self.providers.values() for m in s.models]
        pool = list(self._tags) + list(self.providers) + ids
        close = difflib.get_close_matches(q.lower(), pool, n=3, cutoff=0.5)
        for i in ids:  # also compare against the vendor-less tail, e.g. "nemotron-3-ultra..."
            tail = i.rsplit("/", 1)[-1].replace(":free", "")
            if i not in close and difflib.SequenceMatcher(None, q.lower(), tail.lower()[: len(q) + 2]).ratio() > 0.75:
                close.append(i)
        close = close[:3]
        hint = " Did you mean: %s?" % ", ".join(repr(c) for c in close) if close else ""
        return "unknown model %r.%s Try llmf.models() to list what is available." % (q, hint)


def _dedupe(targets: List[Target]) -> List[Target]:
    seen = set()
    out: List[Target] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
