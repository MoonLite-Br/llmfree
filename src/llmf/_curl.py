"""Optional browser-like transport on top of ``curl_cffi`` (never imported unless asked for).

``curl_cffi`` talks through libcurl-impersonate: TLS/HTTP2 fingerprints match a real Chrome,
which is what some sites check besides the headers. It is *not* a dependency of llmf:
``pip install "llmf[stealth]"`` (or ``pip install curl_cffi``) enables it, and everything keeps
working on the stdlib transport where it cannot be installed (e.g. some Termux/Android setups).
"""

from __future__ import annotations

import socket
from typing import Any, Dict, Iterator, List, Optional

from ._version import __version__


def load():
    """The ``curl_cffi.requests`` module, or ``None`` when it is not installed / unusable."""
    try:
        from curl_cffi import requests  # type: ignore

        return requests
    except Exception:  # ImportError, or a broken native build
        return None


def version() -> Optional[str]:
    try:
        import curl_cffi  # type: ignore

        return str(getattr(curl_cffi, "__version__", "?"))
    except Exception:
        return None


class Unusable(Exception):
    """The curl_cffi call failed in a way that is not an HTTP/network problem (API mismatch...)."""


class Headers(dict):
    """Case-insensitive ``get`` over a plain dict (what ``decode_body`` needs)."""

    def __init__(self, items: Any) -> None:
        super().__init__()
        for k, v in dict(items or {}).items():
            super().__setitem__(str(k).lower(), str(v))

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(str(key).lower(), default)


class CurlResponse:
    """Just enough of ``http.client.HTTPResponse`` for llmf's adapters."""

    def __init__(self, raw: Any, status: int) -> None:
        self._raw = raw
        self.status = self.code = status
        h = Headers(getattr(raw, "headers", None))
        h.pop("content-encoding", None)      # libcurl already decoded the body
        h.pop("content-length", None)
        self.headers = h
        self._chunks: Optional[Iterator[bytes]] = None
        self._buf = b""
        self._done = False

    # -- raw chunks as they arrive
    def _next_chunk(self) -> bytes:
        if self._done:
            return b""
        try:
            if self._chunks is None:
                self._chunks = iter(self._raw.iter_content(chunk_size=None))
            return next(self._chunks, b"") or b""
        except StopIteration:
            self._done = True
            return b""
        except Exception as e:
            self._done = True
            raise _as_oserror(e) from None

    def read1(self, n: int = 8192) -> bytes:
        if self._buf:
            out, self._buf = self._buf[:n], self._buf[n:]
            return out
        chunk = self._next_chunk()
        if not chunk:
            self._done = True
            return b""
        if len(chunk) > n:
            chunk, self._buf = chunk[:n], chunk[n:]
        return chunk

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            parts = [self._buf]
            self._buf = b""
            while True:
                c = self._next_chunk()
                if not c:
                    break
                parts.append(c)
            self._done = True
            return b"".join(parts)
        while len(self._buf) < n:
            c = self._next_chunk()
            if not c:
                break
            self._buf += c
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def __iter__(self) -> Iterator[bytes]:
        """Lines *including* their ``\\n`` (SSE parsers rely on blank lines)."""
        pending = b""
        while True:
            nl = pending.find(b"\n")
            while nl >= 0:
                yield pending[:nl + 1]
                pending = pending[nl + 1:]
                nl = pending.find(b"\n")
            c = self.read1(8192)
            if not c:
                if pending:
                    yield pending
                return
            pending += c

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass

    def __enter__(self) -> "CurlResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _is_curl_error(e: BaseException) -> bool:
    return type(e).__module__.split(".")[0] == "curl_cffi"


def _as_oserror(e: BaseException) -> BaseException:
    name = type(e).__name__.lower()
    if "timeout" in name or getattr(e, "code", None) == 28:
        return socket.timeout(str(e) or "timed out")
    return ConnectionError(str(e) or type(e).__name__)


def open_url(url: str, *, headers: Dict[str, str], data: Optional[bytes], timeout: float,
             proxy: Optional[str], impersonate: str, http_failure: Any) -> CurlResponse:
    """Send the request; ``http_failure`` is ``_http.HTTPFailure`` (passed in to avoid a cycle)."""
    requests = load()
    if requests is None:
        raise Unusable("curl_cffi is not installed (pip install 'llmf[stealth]')")
    hdrs = {k: v for k, v in headers.items()
            if not (k.lower() == "user-agent" and "llmf/%s" % __version__ in v)}   # the profile brings its own UA
    kw: Dict[str, Any] = dict(headers=hdrs, timeout=timeout, stream=True, allow_redirects=True)
    if impersonate:
        kw["impersonate"] = impersonate
    if proxy:
        kw["proxies"] = {"http": proxy, "https": proxy}
    if data is not None:
        kw["data"] = data
    try:
        raw = requests.request("POST" if data is not None else "GET", url, **kw)
    except Exception as e:
        if not _is_curl_error(e):
            raise Unusable("%s: %s" % (type(e).__name__, e)) from None
        name = type(e).__name__.lower()
        if "timeout" in name or getattr(e, "code", None) == 28:
            raise http_failure(None, str(e) or "timed out", "timeout") from None
        raise http_failure(None, str(e), "network") from None
    status = getattr(raw, "status_code", None)
    if not isinstance(status, int):
        raise Unusable("response has no status_code")
    resp = CurlResponse(raw, status)
    if status >= 400:
        try:
            body = resp.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            resp.close()
        raise http_failure(status, body)
    return resp
