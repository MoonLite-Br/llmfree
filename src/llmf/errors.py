"""Exception hierarchy for llmf."""

from __future__ import annotations

from typing import List, Optional


class LLMFError(Exception):
    """Base class for every error raised by llmf."""


class ModelNotFound(LLMFError, ValueError):
    """The requested model / alias / provider could not be resolved."""


class ProviderError(LLMFError):
    """A single provider/model attempt failed.

    Attributes:
        provider: provider name (e.g. ``"ovh"``).
        model: model id that was requested.
        status: HTTP status, or ``None`` for network/timeout/parse problems.
        code: provider-specific error code if one was reported.
        retryable: whether trying the *same* target again may help.
        scope: ``"provider"`` (whole endpoint looks unhealthy) or ``"model"``.
        cooldown: seconds the target should be deprioritised after this error.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.message = message
        self.status = status
        self.code = code
        self.retryable, self.scope, self.cooldown = _classify(status, code)
        super().__init__("%s/%s: %s" % (provider, model, message))


class AllProvidersFailed(LLMFError):
    """Every candidate was tried and none produced an answer."""

    def __init__(self, errors: List[ProviderError], note: str = "") -> None:
        self.errors = list(errors)
        lines = ["  - %s" % e for e in self.errors] or ["  (no candidates were available)"]
        head = "all providers failed" + (" (%s)" % note if note else "")
        super().__init__(head + ":\n" + "\n".join(lines))


_RATE_CODES = {"insufficient_credits", "rate_limit_error", "rate_limited", "rate_limit_exceeded"}
_TRANSIENT_CODES = {"FREE_MODEL_FAILED"}


def _classify(status: Optional[int], code: Optional[str]):
    """Return ``(retryable, scope, cooldown_seconds)`` for an error."""
    if code == "daily_limit":  # free daily quota used up: do not bother again for hours
        return False, "provider", 6 * 3600.0
    if status == 429 or (code or "") in _RATE_CODES:
        return False, "provider", 60.0
    if status is None:  # network / timeout / unparsable
        return True, "provider", 20.0
    if status in (408, 425) or status >= 500:
        return True, "provider", 20.0
    if code in _TRANSIENT_CODES:
        return True, "model", 20.0
    return False, "model", 30.0
