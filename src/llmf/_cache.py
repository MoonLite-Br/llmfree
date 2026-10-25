"""On-disk health/latency cache written by ``llmf doctor`` and read by the Client."""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

MAX_AGE = 24 * 3600.0


def cache_dir() -> Optional[str]:
    """Directory for cache files, or ``None`` when caching is disabled."""
    if os.environ.get("LLMF_NO_CACHE"):
        return None
    d = os.environ.get("LLMF_CACHE_DIR")
    if not d:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        d = os.path.join(base, "llmf")
    return d


def load(directory: Optional[str]) -> List[Dict[str, Any]]:
    """Recent results (``provider``, ``model``, ``ok``, ``latency``) or ``[]``."""
    if not directory:
        return []
    try:
        with open(os.path.join(directory, "health.json"), encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - float(data.get("checked_at", 0)) > MAX_AGE:
            return []
        return [r for r in data.get("results", []) if isinstance(r, dict)]
    except (OSError, ValueError, TypeError):
        return []


def save(directory: Optional[str], results: List[Dict[str, Any]]) -> Optional[str]:
    """Atomically write results; returns the file path (or ``None`` if it cannot)."""
    if not directory:
        return None
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "health.json")
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"checked_at": time.time(), "results": results}, f, ensure_ascii=False)
        os.replace(tmp, path)
        return path
    except OSError:
        return None


# ---------------------------------------------------------------- survival history
HISTORY_WINDOW = 20      # keep the last N doctor results per model
MIN_SAMPLES = 3          # a model needs this many samples before its rate demotes it
MIN_RATE = 0.5           # ... and a success rate below this demotes it


def load_history(directory: Optional[str]) -> Dict[str, str]:
    """``{"provider/model": "1101..."}`` (newest last; ``1`` = answered, ``0`` = failed)."""
    if not directory:
        return {}
    try:
        with open(os.path.join(directory, "history.json"), encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and set(v) <= {"0", "1"}}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def record(directory: Optional[str], rows: List[Dict[str, Any]]) -> None:
    """Append one doctor result per model to the survival history."""
    if not directory or not rows:
        return
    hist = load_history(directory)
    for r in rows:
        try:
            key = "%s/%s" % (r["provider"], r["model"])
        except KeyError:
            continue
        hist[key] = (hist.get(key, "") + ("1" if r.get("ok") else "0"))[-HISTORY_WINDOW:]
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, os.path.join(directory, "history.json"))
    except OSError:
        pass


def rate(history: str) -> Optional[float]:
    return history.count("1") / len(history) if history else None


def unreliable(history: str) -> bool:
    """Enough samples and a low success rate."""
    return len(history) >= MIN_SAMPLES and history.count("1") / len(history) < MIN_RATE
