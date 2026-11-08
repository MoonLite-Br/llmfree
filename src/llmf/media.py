"""Image, speech (TTS) and video generation on free endpoints (stdlib only).

    >>> import llmf
    >>> r = llmf.image("a red fox in the snow", save="fox.png")
    >>> r.url, r.path
    >>> llmf.tts("Xin chao", voice="af_heart", save="hello.mp3")
    >>> llmf.video("a cat running in slow motion", duration=5, save="cat.mp4")

Currently backed by free.ai (``https://api.free.ai``). Its documentation asks for an API key
(``sk-free-...``): pass ``api_key=`` or set ``LLMF_FREEAI_KEY``; without one llmf tries anonymously and
tells you plainly if the server refuses. Free quota is small (about 30,000 tokens/day) and video is expensive.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from . import _http
from .errors import LLMFError, ProviderError

MAX_DOWNLOAD = 300 * 1024 * 1024
_URL_KEYS = {
    "image": ("image_url", "url", "image"),
    "tts": ("audio_url", "url", "audio"),
    "video": ("video_url", "url", "video"),
}
_PENDING = {"pending", "queued", "processing", "running", "in_progress", "starting", "submitted", "created"}
_FAILED = {"failed", "error", "cancelled", "canceled", "rejected"}

# provider -> kind -> (path, default model, request builder)
_FREEAI = "https://api.free.ai"
SPECS: Dict[str, Dict[str, Any]] = {
    "freeai": {
        "base_url": _FREEAI,
        "key_env": "LLMF_FREEAI_KEY",
        "status_path": "/v1/status/%s/",
        "image": {"path": "/v1/image/generate/", "model": "sdxl", "timeout": 180.0},
        "tts": {"path": "/v1/tts/", "model": "kokoro", "timeout": 90.0, "voice": "af_heart"},
        "video": {"path": "/v1/video/generate/", "model": "cogvideox", "timeout": 360.0},
    },
}


class MediaResult:
    """Outcome of a generation call. ``str(result)`` is the local path if saved, else the URL."""

    def __init__(self, kind: str, provider: str, model: str, url: str, raw: Any, latency: float,
                 data: Optional[bytes] = None, path: Optional[str] = None) -> None:
        self.kind, self.provider, self.model, self.url = kind, provider, model, url
        self.raw, self.latency, self.data, self.path = raw, latency, data, path

    def __str__(self) -> str:
        return self.path or self.url

    def __repr__(self) -> str:
        return "<MediaResult %s %s/%s %s>" % (self.kind, self.provider, self.model, self.path or self.url or "bytes")

    def save(self, path: str, *, timeout: float = 120.0, proxy: Optional[str] = None) -> str:
        """Write the media to ``path`` (downloads the URL if needed). Returns the path."""
        blob = self.data if self.data is not None else _download(self.url, timeout, proxy)
        _write_atomic(path, blob)
        self.path = path
        return path


def _write_atomic(path: str, blob: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".llmf-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _check_url(url: str) -> str:
    if urlsplit(url).scheme not in ("http", "https"):
        raise LLMFError("refusing to fetch a non-http(s) URL: %r" % url[:80])
    return url


def _download(url: str, timeout: float, proxy: Optional[str]) -> bytes:
    _check_url(url)
    try:
        resp = _http.open_url(url, headers={"User-Agent": _http.DEFAULT_UA, "Accept": "*/*"}, timeout=timeout,
                              proxy=proxy)
    except _http.HTTPFailure as e:
        raise LLMFError("download failed (%s): %s" % (e.status or e.kind, e.body[:120])) from None
    try:
        out, size = [], 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise LLMFError("download larger than %d MB: refusing" % (MAX_DOWNLOAD // 1048576))
            out.append(chunk)
        return b"".join(out)
    finally:
        resp.close()


def _find(obj: Any, keys: Tuple[str, ...], depth: int = 0) -> Optional[Any]:
    """First string value under one of ``keys`` (also looks into ``data[0]``, ``output``, ``result``)."""
    if depth > 3:
        return None
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, list) and v and isinstance(v[0], str):
                return v[0]
        for k in ("data", "output", "result", "results", "images", "audio", "video"):
            if k in obj:
                got = _find(obj[k], keys, depth + 1)
                if got:
                    return got
    elif isinstance(obj, list) and obj:
        return _find(obj[0], keys, depth + 1)
    return None


def _b64(obj: Any) -> Optional[bytes]:
    v = _find(obj, ("b64_json", "audio_base64", "image_base64", "base64"))
    if not v:
        return None
    try:
        return base64.b64decode(v.split(",", 1)[-1], validate=False)
    except ValueError:
        return None


def _status(obj: Any) -> str:
    if isinstance(obj, dict):
        s = obj.get("status") or obj.get("state")
        if isinstance(s, str):
            return s.lower()
    return ""


def _job_id(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        for k in ("job_id", "task_id", "request_id", "id"):
            v = obj.get(k)
            if isinstance(v, (str, int)) and str(v):
                return str(v)
    return None


class Media:
    """``client.image(...)``, ``client.tts(...)``, ``client.video(...)``: see the module docstring."""

    def __init__(self, client: Any) -> None:
        self._c = client

    # -- plumbing ---------------------------------------------------------------------------------
    def _headers(self, spec: Dict[str, Any], api_key: Optional[str]) -> Dict[str, str]:
        h = {"User-Agent": self._c.user_agent, "Accept": "application/json", "Content-Type": "application/json"}
        key = api_key or os.environ.get(spec.get("key_env", ""))
        if key:
            h["Authorization"] = "Bearer " + key
        return h

    def _post(self, provider: str, model: str, url: str, headers: Dict[str, str], body: Optional[dict],
              timeout: float) -> Any:
        try:
            resp = _http.open_url(url, headers=headers, data=None if body is None else json.dumps(body).encode(),
                                  timeout=timeout, proxy=self._c.proxy)
        except _http.HTTPFailure as e:
            raise ProviderError(provider, model, _explain(e), status=e.status) from None
        try:
            text = _http.decode_body(resp)
        finally:
            resp.close()
        try:
            return json.loads(text)
        except ValueError:
            raise ProviderError(provider, model, "not JSON: %s" % text[:120]) from None

    def _generate(self, kind: str, provider: str, model: Optional[str], payload: Dict[str, Any],
                  save: Optional[str], api_key: Optional[str], timeout: Optional[float], wait: float) -> MediaResult:
        spec = SPECS.get(provider)
        if spec is None or kind not in spec:
            raise LLMFError("provider %r does not support %s generation (supported: %s)" % (
                provider, kind, ", ".join(sorted(p for p, s in SPECS.items() if kind in s)) or "none"))
        ks = spec[kind]
        model = model or ks["model"]
        payload = dict(payload, model=model)
        tmo = float(timeout or ks["timeout"])
        base = spec["base_url"]
        headers = self._headers(spec, api_key)
        t0 = time.monotonic()
        obj = self._post(provider, model, base + ks["path"], headers, payload, tmo)
        keys = _URL_KEYS[kind]
        url, data = _find(obj, keys), _b64(obj)
        if not url and data is None:
            jid = _job_id(obj)
            if jid is None or _status(obj) in _FAILED:
                raise ProviderError(provider, model, _api_error(obj) or "no %s in the response: %s" % (
                    kind, json.dumps(obj)[:160]))
            url, data, obj = self._poll(kind, provider, model, base + spec["status_path"] % jid, headers, keys, wait)
        elif url:
            url = urljoin(base + "/", url)
        res = MediaResult(kind, provider, model, url or "", obj, time.monotonic() - t0, data=data)
        if url:
            _check_url(url)
        if save:
            res.save(save, timeout=max(60.0, tmo), proxy=self._c.proxy)
        return res

    def _poll(self, kind: str, provider: str, model: str, url: str, headers: Dict[str, str],
              keys: Tuple[str, ...], wait: float) -> Tuple[str, Optional[bytes], Any]:
        end = time.monotonic() + wait
        delay = 2.0
        h = dict(headers)
        h.pop("Content-Type", None)
        while time.monotonic() < end:
            time.sleep(delay)
            delay = min(delay * 1.5, 10.0)
            obj = self._post(provider, model, url, h, None, 30.0)
            st = _status(obj)
            if st in _FAILED:
                raise ProviderError(provider, model, _api_error(obj) or "the job failed (%s)" % st)
            found, data = _find(obj, keys), _b64(obj)
            if found or data is not None:
                return (urljoin(url, found) if found else ""), data, obj
            if st and st not in _PENDING and st not in ("completed", "complete", "done", "succeeded", "success"):
                raise ProviderError(provider, model, "unexpected job state %r" % st)
        raise LLMFError("%s generation did not finish within %.0f s (job %s)" % (kind, wait, url.rsplit("/", 2)[-2]))

    # -- public API -------------------------------------------------------------------------------
    def image(self, prompt: str, *, model: Optional[str] = None, aspect_ratio: Optional[str] = None,
              provider: str = "freeai", save: Optional[str] = None, api_key: Optional[str] = None,
              timeout: Optional[float] = None, wait: float = 180.0) -> MediaResult:
        """Generate an image from ``prompt``; ``save="out.png"`` also downloads it."""
        body: Dict[str, Any] = {"prompt": _need(prompt, "prompt")}
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        return self._generate("image", provider, model, body, save, api_key, timeout, wait)

    def tts(self, text: str, *, voice: Optional[str] = None, model: Optional[str] = None,
            provider: str = "freeai", save: Optional[str] = None, api_key: Optional[str] = None,
            timeout: Optional[float] = None, wait: float = 120.0) -> MediaResult:
        """Speak ``text``; ``save="out.mp3"`` also downloads the audio."""
        ks = SPECS.get(provider, {}).get("tts", {})
        body = {"text": _need(text, "text"), "voice": voice or ks.get("voice", "default")}
        return self._generate("tts", provider, model, body, save, api_key, timeout, wait)

    def video(self, prompt: str, *, duration: int = 5, model: Optional[str] = None, provider: str = "freeai",
              save: Optional[str] = None, api_key: Optional[str] = None, timeout: Optional[float] = None,
              wait: float = 600.0) -> MediaResult:
        """Generate a short video (slow and token-hungry on free tiers; ``wait`` bounds polling)."""
        body = {"prompt": _need(prompt, "prompt"), "duration": int(duration)}
        return self._generate("video", provider, model, body, save, api_key, timeout, wait)

    def models(self, kind: Optional[str] = None) -> List[str]:
        """Known ``provider/model`` ids for ``kind`` (image | tts | video); defaults only, see the provider for more."""
        out = []
        for p, s in SPECS.items():
            for k in ([kind] if kind else ("image", "tts", "video")):
                if k in s:
                    out.append("%s/%s (%s)" % (p, s[k]["model"], k))
        return out


def _need(v: Any, what: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("%s must be a non-empty string" % what)
    return v


def _api_error(obj: Any) -> str:
    if isinstance(obj, dict):
        e = obj.get("error") or obj.get("message") or obj.get("detail")
        if isinstance(e, dict):
            e = e.get("message")
        if isinstance(e, str):
            return e[:200]
    return ""


def _explain(e: "_http.HTTPFailure") -> str:
    try:
        msg = _api_error(json.loads(e.body)) or e.body[:160]
    except ValueError:
        msg = e.body[:160]
    hint = {401: " (an API key is required: set LLMF_FREEAI_KEY or pass api_key=)",
            403: " (refused: this endpoint may need an API key: LLMF_FREEAI_KEY)",
            402: " (out of free tokens for today)",
            429: " (rate limited, retry later)"}.get(e.status or 0, "")
    return "HTTP %s: %s%s" % (e.status if e.status else e.kind, msg, hint)
