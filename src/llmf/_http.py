"""Tiny stdlib HTTP layer (no third-party dependencies)."""

from __future__ import annotations

import gzip
import http.client
import socket
import ssl
import urllib.error
import urllib.request
from typing import Dict, Optional

from ._version import __version__

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 llmf/%s" % __version__
)

NETWORK_ERRORS = (OSError, http.client.HTTPException, ssl.SSLError, socket.timeout)


class HTTPFailure(Exception):
    """Transport-level failure. ``status is None`` means no HTTP response."""

    def __init__(self, status: Optional[int], body: str = "", kind: str = "http") -> None:
        self.status = status
        self.body = body
        self.kind = kind  # "http" | "timeout" | "network"
        super().__init__("%s %s" % (status if status is not None else kind, body[:120]))


def decode_body(resp) -> str:
    data = resp.read()
    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
        try:
            data = gzip.decompress(data)
        except OSError:
            pass
    return data.decode("utf-8", "replace")


def build_opener(proxy: Optional[str] = None, *handlers) -> urllib.request.OpenerDirector:
    """Opener honouring an explicit ``proxy`` (http/https/socks*), else the environment's."""
    hs = list(handlers)
    if proxy and proxy.lower().startswith("socks"):
        from . import _socks  # lazy: only when a SOCKS proxy is used

        sp = _socks.parse(proxy)
        # ProxyHandler({}) switches off HTTP(S)_PROXY from the environment.
        hs += [urllib.request.ProxyHandler({}), _socks.SocksHTTPHandler(sp), _socks.SocksHTTPSHandler(sp)]
    elif proxy:
        hs.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*hs)


def check_proxy(proxy: Optional[str]) -> Optional[str]:
    if isinstance(proxy, str) and proxy.strip().lower() in ("auto", "rotate", "random"):
        raise ValueError("proxy='auto' is not supported: llmf never picks or rotates public "
                         "proxies for you. Pass your own proxy URL, e.g. http://host:port")
    if proxy and not proxy.lower().startswith(("http://", "https://", "socks4://", "socks4a://",
                                              "socks5://", "socks5h://")):
        raise ValueError("proxy must look like http://host:port, https://host:port or "
                         "socks5://host:port (also socks5h, socks4, socks4a): %r" % proxy)
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
