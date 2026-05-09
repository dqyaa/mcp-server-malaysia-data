"""Typed domain exceptions.

Layered exception hierarchy lets callers catch at any granularity:
    except UpstreamError       # any upstream issue
    except UpstreamTimeout     # only timeouts
    except CircuitOpenError    # only circuit-breaker fast-fail
"""

from __future__ import annotations


class MalaysiaDataError(Exception):
    """Root for every error raised inside this package."""


class UpstreamError(MalaysiaDataError):
    """Any failure caused by an upstream API (BNM, data.gov.my)."""

    def __init__(self, message: str, *, upstream: str, status: int | None = None) -> None:
        super().__init__(message)
        self.upstream = upstream
        self.status = status


class UpstreamTimeout(UpstreamError):
    """Upstream did not respond within the configured timeout."""


class UpstreamUnavailable(UpstreamError):
    """Upstream returned 5xx, network error, or DNS failure."""


class UpstreamInvalidResponse(UpstreamError):
    """Upstream returned 200 but the body did not match the expected schema."""


class RateLimitedError(MalaysiaDataError):
    """Local rate limiter prevented an outbound call."""

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__(f"Rate limited; retry in {retry_after_seconds:.1f}s")
        self.retry_after_seconds = retry_after_seconds


class CircuitOpenError(MalaysiaDataError):
    """Circuit breaker is open; failing fast."""

    def __init__(self, upstream: str, retry_after_seconds: float) -> None:
        super().__init__(f"Circuit open for {upstream}; retry in {retry_after_seconds:.1f}s")
        self.upstream = upstream
        self.retry_after_seconds = retry_after_seconds


class NotFoundError(MalaysiaDataError):
    """Requested data does not exist (e.g. unknown state name)."""
