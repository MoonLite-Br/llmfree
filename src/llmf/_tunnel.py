"""``--cloudflare``: expose the local server through the user's own ``cloudflared`` binary.

llmf never downloads or bundles anything: it looks for ``cloudflared`` on PATH and runs

* a free *quick tunnel* (random ``https://*.trycloudflare.com`` URL, no account), or
* a *named tunnel* with ``--tunnel-token`` (your own domain, configured in the Cloudflare dashboard).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from typing import List, Optional

QUICK_URL = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
NAMED_OK = re.compile(r"registered tunnel connection|connection [0-9a-f-]+ registered", re.I)


class TunnelError(RuntimeError):
    pass


def find_cloudflared() -> Optional[str]:
    return os.environ.get("CLOUDFLARED") or shutil.which("cloudflared")


class Tunnel:
    def __init__(self, port: int, *, token: Optional[str] = None, binary: Optional[str] = None,
                 scheme: str = "http") -> None:
        self.port, self.token, self.scheme = port, token, scheme
        self.binary = binary or find_cloudflared()
        self.proc: Optional[subprocess.Popen] = None
        self.url: Optional[str] = None
        self.lines: List[str] = []
        self._ready = threading.Event()

    def argv(self) -> List[str]:
        if not self.binary:
            raise TunnelError(
                "cloudflared was not found on PATH. Install it (Termux: `pkg install cloudflared`; "
                "other systems: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/"
                "downloads/) or set CLOUDFLARED=/path/to/cloudflared")
        base = [self.binary, "tunnel", "--no-autoupdate"]
        if self.token:
            return base + ["run", "--token", self.token]
        return base + ["--url", "%s://127.0.0.1:%d" % (self.scheme, self.port)]

    def start(self, timeout: float = 60.0) -> Optional[str]:
        """Start the tunnel; returns the public URL (``None`` for a named tunnel: you know your hostname)."""
        argv = self.argv()
        if self.scheme == "https" and not self.token:
            argv += ["--no-tls-verify"]            # our own (possibly self-signed) local certificate
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"))
        threading.Thread(target=self._pump, daemon=True).start()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._ready.wait(0.2):
                return self.url
            if self.proc.poll() is not None:
                raise TunnelError("cloudflared exited with code %s:\n%s" % (self.proc.returncode,
                                                                             "\n".join(self.lines[-8:])))
        self.stop()
        raise TunnelError("cloudflared did not report a tunnel within %.0fs:\n%s" % (timeout, "\n".join(self.lines[-8:])))

    def _pump(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            self.lines = (self.lines + [line])[-60:]
            if not self._ready.is_set():
                if self.token:
                    if NAMED_OK.search(line):
                        self._ready.set()
                else:
                    m = QUICK_URL.search(line)
                    if m:
                        self.url = m.group(0)
                        self._ready.set()

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
                p.kill()
            except OSError:
                pass
