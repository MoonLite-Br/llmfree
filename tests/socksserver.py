"""Minimal SOCKS4/4a/5 server for tests; every destination is redirected to ``target``."""

import socket
import struct
import threading


def _recv(c, n):
    b = b""
    while len(b) < n:
        d = c.recv(n - len(b))
        if not d:
            raise OSError("eof")
        b += d
    return b


def _pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()


class SocksServer:
    def __init__(self, target, creds=None):
        self.target, self.creds, self.requests = target, creds, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    def close(self):
        self.sock.close()

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        try:
            first = _recv(c, 1)
            if first == b"\x05":
                self._v5(c)
            else:
                self._v4(c)
        except OSError:
            c.close()

    def _relay(self, c):
        up = socket.create_connection(self.target, 5)
        threading.Thread(target=_pipe, args=(c, up), daemon=True).start()
        _pipe(up, c)

    def _v5(self, c):
        n = _recv(c, 1)[0]
        methods = _recv(c, n)
        if self.creds:
            if 2 not in methods:
                c.sendall(b"\x05\xff")
                return
            c.sendall(b"\x05\x02")
            _recv(c, 1)
            user = _recv(c, _recv(c, 1)[0]).decode()
            pw = _recv(c, _recv(c, 1)[0]).decode()
            if (user, pw) != self.creds:
                c.sendall(b"\x01\x01")
                return
            c.sendall(b"\x01\x00")
        else:
            c.sendall(b"\x05\x00")
        _, cmd, _, atyp = _recv(c, 4)
        if atyp == 1:
            host = socket.inet_ntoa(_recv(c, 4))
        elif atyp == 3:
            host = _recv(c, _recv(c, 1)[0]).decode()
        else:
            host = "ipv6"
        _recv(c, 2)
        self.requests.append(("5", atyp, host))
        c.sendall(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
        self._relay(c)

    def _v4(self, c):
        _recv(c, 1 + 2)  # cmd + port (version byte already read)
        ip = _recv(c, 4)
        while _recv(c, 1) != b"\x00":  # userid
            pass
        host = socket.inet_ntoa(ip)
        if ip[:3] == b"\x00\x00\x00" and ip[3] != 0:  # socks4a
            name = b""
            while True:
                ch = _recv(c, 1)
                if ch == b"\x00":
                    break
                name += ch
            host = name.decode()
        self.requests.append(("4", None, host))
        c.sendall(b"\x00\x5a" + b"\x00" * 6)
        self._relay(c)
