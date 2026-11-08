"""Tiny stdlib HTTP layer (no third-party dependencies)."""

from __future__ import annotations

import http.client
import logging
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
import zlib
from typing import Dict, Iterator, Optional
from urllib.parse import urlsplit

from ._version import __version__

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 llmf/%s" % __version__
)

log = logging.getLogger("llmf")

TRANSPORTS = ("urllib", "curl_cffi", "auto")
_transport = {"mode": os.environ.get("LLMF_TRANSPORT") or "urllib",
              "impersonate": os.environ.get("LLMF_IMPERSONATE") or "chrome",
              "broken": False}


def configure_transport(mode: Optional[str] = None, impersonate: Optional[str] = None) -> None:
    """Process-wide transport: ``"urllib"`` (default, stdlib), ``"curl_cffi"`` (browser TLS fingerprint,
    strict) or ``"auto"`` (curl_cffi when installed and working, else stdlib)."""
    if mode is not None:
        if mode not in TRANSPORTS:
            raise ValueError("transport must be one of %s" % ", ".join(TRANSPORTS))
        _transport["mode"] = mode
        _transport["broken"] = False
    if impersonate is not None:
        _transport["impersonate"] = impersonate


def transport_info() -> Dict[str, object]:
    from . import _curl

    ver = _curl.version()
    mode = str(_transport["mode"])
    active = "curl_cffi" if mode != "urllib" and ver and not _transport["broken"] else "urllib"
    return {"mode": mode, "active": active, "impersonate": _transport["impersonate"],
            "curl_cffi": ver}


NETWORK_ERRORS = (OSError, http.client.HTTPException, ssl.SSLError, socket.timeout)


class HTTPFailure(Exception):
    """Transport-level failure. ``status is None`` means no HTTP response."""

    def __init__(self, status: Optional[int], body: str = "", kind: str = "http") -> None:
        self.status = status
        self.body = body
        self.kind = kind  # "http" | "timeout" | "network"
        super().__init__("%s %s" % (status if status is not None else kind, body[:120]))


MAX_BODY = 32 * 1024 * 1024      # a chat / model-list / job answer is never this big
MAX_LINE = 1024 * 1024           # one SSE line
MAX_STREAM_SECONDS = 900.0       # a stream that drips forever is cut off


def decode_body(resp, limit: int = MAX_BODY) -> str:
    """Read a whole (small) body: refuses anything larger than ``limit`` bytes, also after gunzip."""
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise HTTPFailure(None, "response larger than %d MB" % (limit // 1048576), "network")
    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            out = d.decompress(data, limit + 1)
            if len(out) > limit or d.unconsumed_tail:
                raise HTTPFailure(None, "decompressed response larger than %d MB" % (limit // 1048576), "network")
            data = out
        except zlib.error:
            pass
    return data.decode("utf-8", "replace")


def iter_lines(resp, *, max_line: int = MAX_LINE, max_total: int = MAX_BODY,
               max_seconds: float = MAX_STREAM_SECONDS) -> Iterator[bytes]:
    """Lines of a streaming body (``\\n`` kept), with caps on line size, total size and wall time."""
    end = time.monotonic() + max_seconds
    total = 0
    readline = getattr(resp, "readline", None)
    source = (iter(lambda: readline(max_line + 1), b"") if callable(readline) else iter(resp))
    for line in source:
        total += len(line)
        if len(line) > max_line or total > max_total:
            raise ConnectionError("stream line/size limit exceeded")
        if time.monotonic() > end:
            raise socket.timeout("stream exceeded %.0f s" % max_seconds)
        yield line


def redact_proxy(proxy: str) -> str:
    """``socks5://user:secret@host:1`` -> ``socks5://user:***@host:1`` (for messages and logs)."""
    try:
        parts = urlsplit(proxy)
        if parts.password:
            netloc = parts.netloc.replace(":" + parts.password + "@", ":***@", 1)
            return parts._replace(netloc=netloc).geturl()
    except ValueError:
        pass
    return proxy


class _ExplicitProxyHandler(urllib.request.ProxyHandler):
    """Like ProxyHandler, but an explicit ``proxy=`` is never skipped because of ``no_proxy``."""

    def proxy_open(self, req, proxy, type):  # noqa: A002 - signature fixed by urllib
        import base64
        from urllib.parse import unquote

        orig_type = req.type
        proxy_type, user, password, hostport = urllib.request._parse_proxy(proxy)  # type: ignore[attr-defined]
        if proxy_type is None:
            proxy_type = orig_type
        if user and password:
            creds = base64.b64encode(("%s:%s" % (unquote(user), unquote(password))).encode()).decode()
            req.add_header("Proxy-authorization", "Basic " + creds)
        req.set_proxy(hostport, proxy_type)
        if orig_type == proxy_type or orig_type == "https":
            return None
        return self.parent.open(req, timeout=req.timeout)


def build_opener(proxy: Optional[str] = None, *handlers) -> urllib.request.OpenerDirector:
    """Opener honouring an explicit ``proxy`` (http/https/socks*), else the environment's."""
    hs = list(handlers)
    if proxy and proxy.lower().startswith("socks"):
        from . import _socks  # lazy: only when a SOCKS proxy is used

        sp = _socks.parse(proxy)
        # ProxyHandler({}) switches off HTTP(S)_PROXY from the environment.
        hs += [urllib.request.ProxyHandler({}), _socks.SocksHTTPHandler(sp), _socks.SocksHTTPSHandler(sp)]
    elif proxy:
        hs.append(_ExplicitProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*hs)


def check_proxy(proxy: Optional[str]) -> Optional[str]:
    if isinstance(proxy, str) and proxy.strip().lower() in ("auto", "rotate", "random"):
        raise ValueError("proxy='auto' is not supported: llmf never picks or rotates public "
                         "proxies for you. Pass your own proxy URL, e.g. http://host:port")
    if proxy and not proxy.lower().startswith(("http://", "https://", "socks4://", "socks4a://",
                                              "socks5://", "socks5h://")):
        raise ValueError("proxy must look like http://host:port, https://host:port or "
                         "socks5://host:port (also socks5h, socks4, socks4a): %r" % redact_proxy(proxy))
    if proxy and proxy.lower().startswith("socks"):
        from . import _socks

        _socks.parse(proxy)  # validate early
    return proxy


def open_url(
    url: str,
    *,
    headers: Dict[str, str],
    data: Optional[bytes] = None,
    timeout: float = 60.0,
    proxy: Optional[str] = None,
    opener: Optional[urllib.request.OpenerDirector] = None,
):
    """Open ``url`` and return the response object (caller must close it)."""
    if urlsplit(url).scheme.lower() not in ("http", "https"):     # never file://, ftp://, ...
        raise HTTPFailure(None, "refusing a non-http(s) URL", "network")
    mode = _transport["mode"]
    if opener is None and mode != "urllib" and not _transport["broken"]:
        from . import _curl

        try:
            return _curl.open_url(url, headers=headers, data=data, timeout=timeout, proxy=proxy,
                                  impersonate=str(_transport["impersonate"]), http_failure=HTTPFailure)
        except _curl.Unusable as e:
            if mode == "curl_cffi":
                raise HTTPFailure(None, "curl_cffi transport unusable: %s" % e, "network") from None
            _transport["broken"] = True      # "auto": remember and use the stdlib from now on
            log.warning("curl_cffi unusable (%s); falling back to urllib", e)
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        if opener is None:
            opener = build_opener(proxy)
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            body = decode_body(e)
        except Exception:  # pragma: no cover - body unreadable
            body = ""
        raise HTTPFailure(e.code, body) from None
    except urllib.error.URLError as e:
        reason = e.reason
        kind = "timeout" if isinstance(reason, (socket.timeout, TimeoutError)) else "network"
        raise HTTPFailure(None, str(reason), kind) from None
    except (socket.timeout, TimeoutError) as e:
        raise HTTPFailure(None, str(e) or "timed out", "timeout") from None
    except NETWORK_ERRORS as e:
        raise HTTPFailure(None, str(e), "network") from None
