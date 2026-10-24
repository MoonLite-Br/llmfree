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
