"""Security building blocks for ``llmf serve`` (stdlib only).

* :class:`RateLimiter` – token bucket per key (IP, API key id, ...).
* :class:`BanList` – temporary block after repeated authentication failures.
* :func:`parse_networks` / :func:`ip_in` – allow/deny lists in CIDR notation.
* :class:`Antibot` – stateless proof-of-work (or Cloudflare Turnstile) that turns a visitor
  into a short-lived, IP-bound session token, so a public web chat is not open to scripts.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
SESSION_PREFIX = "llmf1."


# --------------------------------------------------------------------------- helpers
def key_id(secret: str) -> str:
    """Short, non-reversible id for logs and rate-limit buckets (never log the key itself)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]


def new_api_key() -> str:
    return "llmf-" + secrets.token_urlsafe(24)


def parse_networks(items: Iterable[str]) -> List[Any]:
    out = []
    for raw in items:
        for item in str(raw).split(","):
            item = item.strip()
            if not item:
                continue
            try:
                out.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                raise ValueError("not an IP address or CIDR range: %r" % item) from None
    return out


def _addr(ip: str):
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(a, "ipv4_mapped", None)
    return mapped or a


def ip_in(ip: str, nets: List[Any]) -> bool:
    a = _addr(ip)
    return a is not None and any(a in n for n in nets if n.version == a.version)


def is_loopback(ip: str) -> bool:
    a = _addr(ip)
    return a is not None and a.is_loopback


def is_local(ip: str) -> bool:
    a = _addr(ip)
    return a is not None and (a.is_loopback or a.is_private)


# ------------------------------------------------------------------------ rate limit
class RateLimiter:
    """Token bucket: ``per_min`` sustained, ``burst`` at once. ``per_min <= 0`` disables it."""

    def __init__(self, per_min: float, burst: Optional[float] = None, max_keys: int = 20000) -> None:
        self.rate = max(0.0, float(per_min)) / 60.0
        self.burst = float(burst if burst is not None else max(3, int(per_min / 4)))
        self.max_keys = max_keys
        self._b: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.rate > 0

    def allow(self, key: str, cost: float = 1.0) -> Tuple[bool, float]:
        """``(allowed, seconds_until_it_would_be)``."""
        if self.rate <= 0:
            return True, 0.0
        now = time.monotonic()
        with self._lock:
            tokens, last = self._b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._b[key] = (tokens - cost, now)
                ok, wait = True, 0.0
            else:
                self._b[key] = (tokens, now)
                ok, wait = False, (cost - tokens) / self.rate
            if len(self._b) > self.max_keys:
                self._gc(now)
        return ok, wait

    def _gc(self, now: float) -> None:
        idle = self.burst / self.rate
        for k in [k for k, (_t, last) in self._b.items() if now - last >= idle]:
            del self._b[k]
        if len(self._b) > self.max_keys:           # still too many distinct clients: drop the oldest half
            for k, _v in sorted(self._b.items(), key=lambda kv: kv[1][1])[: len(self._b) // 2]:
                del self._b[k]


class BanList:
    """``after`` strikes within ``window`` seconds block an IP for ``duration`` seconds."""

    def __init__(self, after: int = 10, window: float = 600.0, duration: float = 900.0,
                 max_entries: int = 20000) -> None:
        self.after, self.window, self.duration, self.max_entries = after, window, duration, max_entries
        self._strikes: Dict[str, List[float]] = {}
        self._until: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.after > 0

    def banned(self, ip: str) -> float:
        """Seconds left on the ban (0 if none)."""
        if not self.enabled:
            return 0.0
        now = time.monotonic()
        with self._lock:
            left = self._until.get(ip, 0.0) - now
            if left <= 0:
                self._until.pop(ip, None)
                return 0.0
            return left

    def strike(self, ip: str) -> bool:
        """Record a failure; returns True when this one triggered a ban."""
        if not self.enabled:
            return False
        now = time.monotonic()
        with self._lock:
            s = [t for t in self._strikes.get(ip, []) if now - t < self.window] + [now]
            if len(s) >= self.after:
                self._until[ip] = now + self.duration
                self._strikes.pop(ip, None)
                return True
            self._strikes[ip] = s
            if len(self._strikes) > self.max_entries:
                for k in list(self._strikes)[: len(self._strikes) // 2]:
                    del self._strikes[k]
        return False


# ----------------------------------------------------------------------------- antibot
def leading_zero_bits(digest: bytes) -> int:
    n = 0
    for b in digest:
        if b == 0:
            n += 8
            continue
        n += 8 - b.bit_length()
        break
    return n


def _form_post(url: str, fields: Dict[str, str], timeout: float = 10.0) -> Dict[str, Any]:
    import json
    from urllib.parse import urlencode

    from . import _http

    resp = _http.open_url(url, headers={"Content-Type": "application/x-www-form-urlencoded",
                                        "Accept": "application/json"},
                          data=urlencode(fields).encode(), timeout=timeout)
    try:
        return json.loads(_http.decode_body(resp))
    finally:
        resp.close()


class Antibot:
    """Challenge -> proof -> session token, all stateless except a replay cache.

    ``mode``: ``"pow"`` (SHA-256 leading-zero-bits puzzle, no account needed), ``"turnstile"``
    (Cloudflare Turnstile token, verified server-side) or ``"off"`` (sessions without a proof;
    rate limits still apply).
    """

    def __init__(self, mode: str = "pow", bits: int = 16, *, session_ttl: float = 1800.0,
                 challenge_ttl: float = 120.0, bind_ip: bool = True, secret: Optional[bytes] = None,
                 turnstile_secret: Optional[str] = None, turnstile_sitekey: Optional[str] = None,
                 verify_url: str = TURNSTILE_URL,
                 fetch: Optional[Callable[[str, Dict[str, str]], Dict[str, Any]]] = None) -> None:
        if mode not in ("pow", "turnstile", "off"):
            raise ValueError("antibot must be pow, turnstile or off")
        if mode == "turnstile" and not (turnstile_secret and turnstile_sitekey):
            raise ValueError("--antibot turnstile needs --turnstile-secret and --turnstile-sitekey")
        self.mode, self.bits = mode, max(8, min(int(bits), 28))
        self.session_ttl, self.challenge_ttl, self.bind_ip = session_ttl, challenge_ttl, bind_ip
        self.turnstile_secret, self.sitekey = turnstile_secret, turnstile_sitekey
        self.verify_url, self._fetch = verify_url, fetch or _form_post
        self._secret = secret or os.urandom(32)
        self._used: Dict[str, float] = {}
        self._issued: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    # -- crypto helpers
    def _mac(self, *parts: Any) -> str:
        return hmac.new(self._secret, "|".join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()[:32]

    def _iph(self, ip: str) -> str:
        return hashlib.sha256(ip.encode()).hexdigest()[:12] if self.bind_ip else "-"

    def config(self) -> Dict[str, Any]:
        return {"antibot": self.mode, "turnstile_sitekey": self.sitekey if self.mode == "turnstile" else None}

    # -- proof of work
    def difficulty(self, ip: str) -> int:
        """Base bits, +1 per 4 challenges the same IP asked for in the last 5 minutes (max +6)."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._issued.get(ip, []) if now - t < 300]
            recent.append(now)
            self._issued[ip] = recent
            if len(self._issued) > 10000:
                for k in list(self._issued)[:5000]:
                    del self._issued[k]
        return self.bits + min(6, (len(recent) - 1) // 4)

    def challenge(self, ip: str) -> Dict[str, Any]:
        if self.mode != "pow":
            raise ValueError("proof of work is not enabled")
        ts, nonce, bits = int(time.time()), secrets.token_hex(8), self.difficulty(ip)
        mac = self._mac("c", ts, nonce, bits, self._iph(ip))
        return {"challenge": "v1.%d.%s.%d.%s" % (ts, nonce, bits, mac), "bits": bits,
                "expires_in": int(self.challenge_ttl)}

    def _check_pow(self, ip: str, challenge: str, counter: Any) -> None:
        try:
            ver, ts_s, nonce, bits_s, mac = challenge.split(".")
            ts, bits = int(ts_s), int(bits_s)
            counter = int(counter)
        except (ValueError, AttributeError, TypeError):
            raise PermissionError("malformed proof") from None
        if ver != "v1" or counter < 0 or not hmac.compare_digest(mac, self._mac("c", ts, nonce, bits, self._iph(ip))):
            raise PermissionError("invalid challenge")
        if time.time() - ts > self.challenge_ttl or ts > time.time() + 5:
            raise PermissionError("challenge expired")
        digest = hashlib.sha256(("%s:%d" % (challenge, counter)).encode()).digest()
        if leading_zero_bits(digest) < bits:
            raise PermissionError("proof of work not solved")
        now = time.monotonic()
        with self._lock:
            if nonce in self._used:
                raise PermissionError("challenge already used")
            self._used[nonce] = now + self.challenge_ttl
            if len(self._used) > 5000:
                for k in [k for k, v in self._used.items() if v < now]:
                    del self._used[k]

    # -- turnstile
    def _check_turnstile(self, ip: str, token: Any) -> None:
        if not isinstance(token, str) or not token:
            raise PermissionError("missing turnstile token")
        try:
            out = self._fetch(self.verify_url, {"secret": self.turnstile_secret or "", "response": token,
                                                "remoteip": ip})
        except Exception:                        # network trouble must never let a visitor through
            raise PermissionError("could not verify turnstile token") from None
        if not (isinstance(out, dict) and out.get("success") is True):
            raise PermissionError("turnstile rejected the token")

    # -- sessions
    def session(self, ip: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Verify the proof in ``payload`` and mint a session token (raises ``PermissionError``)."""
        if self.mode == "pow":
            self._check_pow(ip, str(payload.get("challenge", "")), payload.get("counter"))
        elif self.mode == "turnstile":
            self._check_turnstile(ip, payload.get("turnstile"))
        exp = int(time.time() + self.session_ttl)
        return {"token": "%s%d.%s" % (SESSION_PREFIX, exp, self._mac("s", exp, self._iph(ip))),
                "expires_in": int(self.session_ttl)}

    def valid_token(self, token: str, ip: str) -> bool:
        if not token.startswith(SESSION_PREFIX):
            return False
        try:
            exp_s, mac = token[len(SESSION_PREFIX):].split(".", 1)
            exp = int(exp_s)
        except ValueError:
            return False
        return exp > time.time() and hmac.compare_digest(mac, self._mac("s", exp, self._iph(ip)))
