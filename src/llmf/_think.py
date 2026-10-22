"""Split ``<think>...</think>`` reasoning out of a (possibly streamed) text."""

from __future__ import annotations

from typing import List

OPEN = "<think>"
CLOSE = "</think>"


def _partial_suffix(s: str, token: str) -> int:
    """Length of the longest proper prefix of ``token`` that ``s`` ends with."""
    for k in range(min(len(token) - 1, len(s)), 0, -1):
        if s.endswith(token[:k]):
            return k
    return 0


class ThinkSplitter:
    """Incremental splitter. ``feed()`` returns the visible text for a chunk."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self._started = False  # visible text has begun (for leading-space trim)
        self.thought: List[str] = []

    def _emit(self, text: str) -> str:
        if not self._started:
            text = text.lstrip()
            if text:
                self._started = True
        return text

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: List[str] = []
        while True:
            if not self._inside:
                i = self._buf.find(OPEN)
                if i >= 0:
                    out.append(self._buf[:i])
                    self._buf = self._buf[i + len(OPEN):]
                    self._inside = True
                    continue
                keep = _partial_suffix(self._buf, OPEN)
                cut = len(self._buf) - keep
                out.append(self._buf[:cut])
                self._buf = self._buf[cut:]
                break
            j = self._buf.find(CLOSE)
            if j >= 0:
                self.thought.append(self._buf[:j])
                self._buf = self._buf[j + len(CLOSE):]
                self._inside = False
                continue
            keep = _partial_suffix(self._buf, CLOSE)
            cut = len(self._buf) - keep
            self.thought.append(self._buf[:cut])
            self._buf = self._buf[cut:]
            break
        return self._emit("".join(out))

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        if self._inside:
            self.thought.append(rest)
            return ""
        return self._emit(rest)

    @property
    def reasoning(self) -> str:
        return "".join(self.thought).strip()


def split_think(text: str):
    """Non-streaming helper -> ``(visible_text, reasoning_or_None)``."""
    # Some templates only emit the closing tag (the opening one is in the prompt).
    if CLOSE in text and OPEN not in text:
        thought, _, text = text.partition(CLOSE)
        return text.strip(), (thought.strip() or None)
    sp = ThinkSplitter()
    visible = sp.feed(text) + sp.flush()
    return visible.strip(), (sp.reasoning or None)
