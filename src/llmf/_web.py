"""Static files, a child "app" process (e.g. ``node main.js``) and a small reverse proxy for ``llmf serve``."""

from __future__ import annotations

import http.client
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

_TYPES = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".map": "application/json",
    ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".wasm": "application/wasm", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".mp3": "audio/mpeg", ".mp4": "video/mp4", ".webm": "video/webm", ".pdf": "application/pdf",
}


def content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _TYPES:
        return _TYPES[ext]
    import mimetypes

    return mimetypes.guess_type(path)[0] or "application/octet-stream"


class StaticSite:
    """Serves a **single file** (only that file, never its folder) or a directory tree.

    Directory mode never follows a path outside the root (``..``, symlinks), never serves dotfiles,
    never lists directories, and falls back to ``index.html`` for extension-less paths (SPA routing).
    """

    def __init__(self, path: str) -> None:
        p = os.path.abspath(os.path.expanduser(path))
        self.single: Optional[str] = None
        self.root: Optional[str] = None
        if os.path.isfile(p):
            self.single = p
        elif os.path.isdir(p):
            self.root = os.path.realpath(p)
        else:
            raise ValueError("web path does not exist: %s" % path)

    def describe(self) -> str:
        return "file %s" % self.single if self.single else "directory %s" % self.root

    def find(self, url_path: str) -> Optional[str]:
        rel = unquote(url_path.split("?", 1)[0])
        if "\x00" in rel or "\\" in rel:
            return None
        if self.single:
            name = os.path.basename(self.single)
            return self.single if rel in ("", "/", "/index.html", "/" + name) else None
        parts = [x for x in rel.split("/") if x not in ("", ".")]
        if any(x == ".." or x.startswith(".") for x in parts):
            return None
        root = self.root or ""
        cand = os.path.realpath(os.path.join(root, *parts)) if parts else root
        if cand != root and not cand.startswith(root + os.sep):
            return None
        if os.path.isdir(cand):
            cand = os.path.join(cand, "index.html")
        if os.path.isfile(cand):
            return cand
        if parts and "." not in parts[-1]:
            idx = os.path.join(root, "index.html")
            if os.path.isfile(idx):
                return idx
        return None


# ----------------------------------------------------------------------------- child app
def resolve_command(command: str) -> List[str]:
    """``"node main.js"`` -> argv. A bare script path gets its interpreter (``.js`` -> node, ``.py`` -> python)."""
    argv = shlex.split(command)
    if not argv:
        raise ValueError("--app needs a command, e.g. --app \"node main.js\"")
    first = argv[0]
    ext = os.path.splitext(first)[1].lower()
    if len(argv) == 1 and os.path.isfile(first):
        if ext in (".js", ".mjs", ".cjs"):
            argv = ["node", first]
        elif ext == ".py":
            argv = [sys.executable, first]
    if shutil.which(argv[0]) is None and not os.path.isfile(argv[0]):
        hint = " (Termux: pkg install nodejs)" if argv[0] in ("node", "npm", "npx") else ""
        raise ValueError("command not found: %s%s" % (argv[0], hint))
    return argv


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class AppProcess:
    """Runs the user's web project as a child process and waits until it listens on ``port``."""

    def __init__(self, command: str, port: int, *, cwd: Optional[str] = None,
                 env: Optional[Dict[str, str]] = None,
                 log: Callable[[str], None] = lambda s: print(s, file=sys.stderr)) -> None:
        self.argv = resolve_command(command)
        self.port, self.log = port, log
        self.cwd = cwd or (os.path.dirname(os.path.abspath(self.argv[-1])) if os.path.isfile(self.argv[-1]) else None)
        self.env = dict(os.environ)
        self.env.update(env or {})
        self.env["PORT"] = str(port)
        self.env.setdefault("HOST", "127.0.0.1")
        self.proc: Optional[subprocess.Popen] = None
        self.tail: List[str] = []

    def start(self, wait: float = 30.0) -> None:
        if port_open(self.port):
            raise RuntimeError("port %d is already in use: pick another with --app-port" % self.port)
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=(os.name == "posix"))
        threading.Thread(target=self._pump, daemon=True).start()
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("the app exited with code %s before listening on port %d:\n%s"
                                   % (self.proc.returncode, self.port, "\n".join(self.tail[-8:])))
            if port_open(self.port):
                return
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("the app did not listen on port %d within %.0fs (does it read the PORT "
                           "environment variable?)\n%s" % (self.port, wait, "\n".join(self.tail[-8:])))

    def _pump(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.tail = (self.tail + [line])[-50:]
                self.log("[app] " + line)

    def stop(self) -> None:
        p = self.proc
        if p is None or p.poll() is not None:
            return
        import signal

        try:
            if os.name == "posix":
                os.killpg(p.pid, signal.SIGTERM)
            else:
                p.terminate()
            p.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
            try:
                if os.name == "posix":
                    os.killpg(p.pid, signal.SIGKILL)
                else:
                    p.kill()
            except (OSError, ProcessLookupError):
                pass


# --------------------------------------------------------------------------- reverse proxy
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
        "transfer-encoding", "upgrade", "host", "content-length"}


def proxy_request(handler: Any, port: int, *, method: str, body: Optional[bytes], client_ip: str,
                  scheme: str, drop_auth: Callable[[str], bool], timeout: float = 120.0) -> int:
    """Forward the request to ``127.0.0.1:port`` and stream the answer back; returns the status."""
    if handler.headers.get("Upgrade", "").lower() == "websocket":
        handler._json(501, {"error": {"message": "WebSocket upgrades are not proxied", "type": "not_implemented"}})
        return 501
    headers: Dict[str, str] = {}
    for k, v in handler.headers.items():
        lk = k.lower()
        if lk in _HOP or lk.startswith("x-forwarded-") or lk == "x-real-ip":
            continue
        if lk == "authorization" and drop_auth(v):
            continue
        headers[k] = v
    host = handler.headers.get("Host", "")
    headers.update({"Host": host, "X-Forwarded-For": client_ip, "X-Real-IP": client_ip,
                    "X-Forwarded-Proto": scheme, "X-Forwarded-Host": host, "Connection": "close"})
    if body is not None:
        headers["Content-Length"] = str(len(body))
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        try:
            conn.request(method, handler.path, body=body, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException):
            handler._json(502, {"error": {"message": "the app is not responding", "type": "bad_gateway"}})
            return 502
        handler.send_response(resp.status)
        chunked = (resp.getheader("Transfer-Encoding") or "").lower() == "chunked"
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in _HOP and not (lk == "content-length" and not chunked):
                continue
            handler.send_header(k, v)
        handler.end_headers()
        if method != "HEAD":
            try:
                while True:
                    chunk = resp.read(16384)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
            except (OSError, http.client.HTTPException):
                pass
        return resp.status
    finally:
        conn.close()
