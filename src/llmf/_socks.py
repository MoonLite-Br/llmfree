"""Pure-stdlib SOCKS4 / SOCKS4a / SOCKS5 / SOCKS5h client for urllib.

    socks5://user:pass@host:1080   (hostnames resolved locally)
    socks5h://host:1080            (hostnames resolved by the proxy)
    socks4://host:1080, socks4a://host:1080
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import struct
import urllib.request
from typing import NamedTuple, Optional
from urllib.parse import unquote, urlsplit

SCHEMES = ("socks4", "socks4a", "socks5", "socks5h")

_SOCKS5_ERRORS = {
    1: "general failure", 2: "connection not allowed by ruleset", 3: "network unreachable",
    4: "host unreachable", 5: "connection refused", 6: "TTL expired",
    7: "command not supported", 8: "address type not supported",
}


class SocksProxy(NamedTuple):
    scheme: str
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]


class SocksError(OSError):
    """Handshake with the SOCKS proxy failed."""


def parse(url: str) -> SocksProxy:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in SCHEMES or not parts.hostname:
        raise ValueError("invalid SOCKS proxy URL: %r" % url)
    return SocksProxy(scheme, parts.hostname, parts.port or 1080,
                      unquote(parts.username) if parts.username else None,
                      unquote(parts.password) if parts.password else None)


def _recv(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise SocksError("proxy closed the connection during the handshake")
        buf += chunk
    return buf


def _is_ip(host: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def connect(proxy: SocksProxy, host: str, port: int, timeout: Optional[float]) -> socket.socket:
    """Open a TCP tunnel to ``host:port`` through ``proxy``; returns the connected socket."""
    sock = socket.create_connection((proxy.host, proxy.port), timeout)
    try:
        if proxy.scheme.startswith("socks5"):
            _socks5(sock, proxy, host, port)
        else:
            _socks4(sock, proxy, host, port)
        return sock
    except BaseException:
        sock.close()
        raise


def _socks5(sock: socket.socket, p: SocksProxy, host: str, port: int) -> None:
    methods = b"\x00\x02" if p.user is not None else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    ver, method = _recv(sock, 2)
    if ver != 5:
        raise SocksError("not a SOCKS5 proxy")
    if method == 2:
        u, pw = (p.user or "").encode(), (p.password or "").encode()
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
        if _recv(sock, 2)[1] != 0:
            raise SocksError("SOCKS5 authentication failed")
    elif method != 0:
        raise SocksError("SOCKS5 proxy offers no acceptable authentication method")
    ip = _is_ip(host)
    if ip is None and p.scheme == "socks5":  # resolve locally unless socks5h
        ip = ipaddress.ip_address(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0])
    if ip is not None:
        addr = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
    else:
        name = host.encode("idna")
        addr = b"\x03" + bytes([len(name)]) + name
    sock.sendall(b"\x05\x01\x00" + addr + struct.pack("!H", port))
    ver, rep, _, atyp = _recv(sock, 4)
    if rep != 0:
        raise SocksError("SOCKS5 connect failed: %s" % _SOCKS5_ERRORS.get(rep, "error %d" % rep))
    skip = {1: 4, 4: 16}.get(atyp)
    if skip is None:
        skip = _recv(sock, 1)[0]
    _recv(sock, skip + 2)


def _socks4(sock: socket.socket, p: SocksProxy, host: str, port: int) -> None:
    user = (p.user or "").encode() + b"\x00"
    ip = _is_ip(host)
    if ip is None and p.scheme == "socks4":
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    if ip is not None:
        if ip.version != 4:
            raise SocksError("SOCKS4 supports IPv4 only")
        req = b"\x04\x01" + struct.pack("!H", port) + ip.packed + user
    else:  # socks4a: let the proxy resolve
        req = b"\x04\x01" + struct.pack("!H", port) + b"\x00\x00\x00\x01" + user + host.encode("idna") + b"\x00"
    sock.sendall(req)
    resp = _recv(sock, 8)
    if resp[1] != 0x5A:
        raise SocksError("SOCKS4 request rejected (code 0x%02x)" % resp[1])


class _HTTPConn(http.client.HTTPConnection):
    def __init__(self, *a, socks: SocksProxy, **kw) -> None:
        super().__init__(*a, **kw)
        self._socks = socks

    def connect(self) -> None:
        self.sock = connect(self._socks, self.host, self.port, self.timeout)


class _HTTPSConn(http.client.HTTPSConnection):
    def __init__(self, *a, socks: SocksProxy, **kw) -> None:
        super().__init__(*a, **kw)
        self._socks = socks

    def connect(self) -> None:
        raw = connect(self._socks, self.host, self.port, self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class SocksHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, proxy: SocksProxy) -> None:
        super().__init__()
        self._proxy = proxy

    def http_open(self, req):
        return self.do_open(_HTTPConn, req, socks=self._proxy)


class SocksHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, proxy: SocksProxy) -> None:
        super().__init__()
        self._proxy = proxy

    def https_open(self, req):
        return self.do_open(_HTTPSConn, req, socks=self._proxy)
