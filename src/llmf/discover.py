"""Optional discovery of live endpoints via the community "stillworks" API.

Best effort: the response shape is parsed tolerantly. Discovered endpoints are
third-party servers you did not choose - use only for non-sensitive prompts.
"""

from __future__ import annotations

import json
from typing import Any, List
from urllib.parse import urlparse

from . import _http
from .providers.base import ModelSpec, ProviderSpec

STILLWORKS_URL = "https://stillworks.supercapybara.com/api/llm/up"


def _rows(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for v in payload.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        if "openai_base_url" in payload:
            return [payload]
    return []


def _chat_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def fetch_specs(timeout: float = 20.0, user_agent: str = _http.DEFAULT_UA,
                url: str = STILLWORKS_URL) -> List[ProviderSpec]:
    resp = _http.open_url(url, headers={"User-Agent": user_agent, "Accept": "application/json"},
                          timeout=timeout)
    try:
        payload = json.loads(_http.decode_body(resp))
    finally:
        resp.close()
    specs: List[ProviderSpec] = []
    seen = set()
    for r in _rows(payload):
        base, model = r.get("openai_base_url"), r.get("model")
        if not base or not model or str(r.get("auth", "none")).lower() != "none":
            continue
        full = _chat_url(str(base))
        if (full, model) in seen:
            continue
        seen.add((full, model))
        caps = r.get("capabilities") or {}
        host = urlparse(full).netloc or "endpoint"
        specs.append(ProviderSpec(
            name="sw-%s-%d" % (host, len(specs)),
            base_url=full, chat_path="",
            models=[ModelSpec(str(model), vision=bool(isinstance(caps, dict) and caps.get("vision")),
                              verified=False)],
            note="discovered via stillworks",
        ))
    return specs
