"""Resilient HTTP transport for upstream API calls.

Combines four production patterns:
1. Connection pooling (httpx.AsyncClient with HTTP/2)
2. Retries with exponential backoff + jitter (tenacity)
3. Token-bucket rate limiting per upstream (aiolimiter)
4. Circuit breaker — fail fast when an upstream is degraded (purgatory)

The order matters: rate-limit wraps circuit-breaker wraps retries wraps the
raw httpx call. Reading bottom-up: the inner-most layer issues one HTTP call;
on transient failure (5xx, timeout) the retry layer tries again with backoff;
if retries exhaust, the circuit breaker increments its failure counter; once
threshold is reached, future calls fail fast (CircuitOpenError) until the
recovery window elapses; rate limiting throttles total outbound RPS.

Why this matters in interviews: every single AI engineer JD I see in 2026
mentions "production-grade external service integration." The candidates who
get hired can describe these four patterns concretely. Most cannot.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from purgatory import AsyncCircuitBreakerFactory
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from malaysia_data_mcp.domain.errors import (
    CircuitOpenError,
    UpstreamInvalidResponse,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from malaysia_data_mcp.infrastructure.observability import (
    circuit_state,
    get_logger,
    upstream_request_duration,
    upstream_requests_total,
)
from malaysia_data_mcp.infrastructure.settings import Settings

logger = get_logger(__name__)


class ResilientHTTPClient:
    """Async HTTP client wrapping httpx with retry/rate-limit/circuit-breaker."""

    def __init__(
        self,
        settings: Settings,
        upstream_name: str,
        rate_limit_per_minute: int,
    ) -> None:
        self._settings = settings
        self._upstream = upstream_name

        # httpx async client — HTTP/2 enabled, connection-pooled.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            http2=True,
            follow_redirects=True,  # data.gov.my redirects /catalogue → /catalogue/
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={
                "User-Agent": f"{settings.service_name}/0.1 (+github.com/aliyaalias19/mcp-server-malaysia-data)",
            },
        )

        # Token-bucket rate limiter — prevents us from hammering free-tier APIs.
        self._limiter = AsyncLimiter(rate_limit_per_minute, time_period=60)

        # Circuit breaker — opens after N consecutive failures, half-opens
        # after recovery window, closes on success.
        self._breaker_factory = AsyncCircuitBreakerFactory(
            default_threshold=settings.circuit_failure_threshold,
            default_ttl=settings.circuit_recovery_seconds,
        )

    async def get_json(
        self,
        path: str,
        *,
        accept: str = "application/json",
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET path, return parsed JSON.

        Raises:
            UpstreamTimeout: server didn't respond in time.
            UpstreamUnavailable: 5xx, network error, DNS failure.
            UpstreamInvalidResponse: 200 but body wasn't valid JSON.
            CircuitOpenError: breaker open; not even attempting the call.
        """
        breaker = await self._breaker_factory.get_breaker(self._upstream)

        async with self._limiter:
            try:
                async with breaker:
                    return await self._get_with_retry(path, accept=accept, params=params)
            except Exception as exc:
                # purgatory raises its own CircuitBreakerError — translate.
                if "circuit" in type(exc).__name__.lower() and "open" in str(exc).lower():
                    circuit_state.labels(upstream=self._upstream).set(2)
                    raise CircuitOpenError(
                        upstream=self._upstream,
                        retry_after_seconds=self._settings.circuit_recovery_seconds,
                    ) from exc
                raise

    async def _get_with_retry(
        self,
        path: str,
        *,
        accept: str,
        params: dict[str, Any] | None,
    ) -> Any:
        """Inner GET with tenacity retry on transient failures."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._settings.http_max_retries + 1),
            wait=wait_exponential_jitter(
                initial=self._settings.http_retry_min_wait_seconds,
                max=self._settings.http_retry_max_wait_seconds,
            ),
            retry=retry_if_exception_type((UpstreamTimeout, UpstreamUnavailable)),
            reraise=True,
        )

        async for attempt in retrying:
            with attempt:
                return await self._raw_get(path, accept=accept, params=params)

    async def _raw_get(
        self,
        path: str,
        *,
        accept: str,
        params: dict[str, Any] | None,
    ) -> Any:
        """Single HTTP GET. Raises typed errors on failure."""
        url = path if path.startswith("http") else f"{path}"
        start = time.perf_counter()

        try:
            response = await self._client.get(
                url,
                headers={"Accept": accept},
                params=params,
            )
        except httpx.TimeoutException as exc:
            duration = time.perf_counter() - start
            upstream_request_duration.labels(upstream=self._upstream).observe(duration)
            upstream_requests_total.labels(upstream=self._upstream, status="timeout").inc()
            logger.warning("upstream_timeout", upstream=self._upstream, path=path, duration=duration)
            raise UpstreamTimeout(
                f"Timeout calling {self._upstream}", upstream=self._upstream
            ) from exc
        except httpx.HTTPError as exc:
            duration = time.perf_counter() - start
            upstream_request_duration.labels(upstream=self._upstream).observe(duration)
            upstream_requests_total.labels(upstream=self._upstream, status="network").inc()
            logger.warning(
                "upstream_network_error",
                upstream=self._upstream,
                path=path,
                error=str(exc),
            )
            raise UpstreamUnavailable(
                f"Network error calling {self._upstream}: {exc}",
                upstream=self._upstream,
            ) from exc

        duration = time.perf_counter() - start
        upstream_request_duration.labels(upstream=self._upstream).observe(duration)

        # Status bucket for metrics
        bucket = (
            "2xx" if 200 <= response.status_code < 300
            else "4xx" if 400 <= response.status_code < 500
            else "5xx"
        )
        upstream_requests_total.labels(upstream=self._upstream, status=bucket).inc()

        if 500 <= response.status_code < 600:
            raise UpstreamUnavailable(
                f"{self._upstream} returned {response.status_code}",
                upstream=self._upstream,
                status=response.status_code,
            )

        if response.status_code >= 400:
            # 4xx is a client error; not retryable. Surface but don't retry.
            raise UpstreamInvalidResponse(
                f"{self._upstream} returned {response.status_code}: {response.text[:200]}",
                upstream=self._upstream,
                status=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamInvalidResponse(
                f"{self._upstream} returned non-JSON body",
                upstream=self._upstream,
                status=response.status_code,
            ) from exc

    async def aclose(self) -> None:
        await self._client.aclose()


# =====================================================================
# Async-friendly module-level lifecycle helpers
# =====================================================================


_clients: dict[str, ResilientHTTPClient] = {}
_clients_lock = asyncio.Lock()


async def get_or_create_client(
    settings: Settings, upstream: str, rate_limit_per_minute: int
) -> ResilientHTTPClient:
    """Module-level singleton-per-upstream client factory."""
    async with _clients_lock:
        if upstream not in _clients:
            _clients[upstream] = ResilientHTTPClient(settings, upstream, rate_limit_per_minute)
        return _clients[upstream]


async def close_all_clients() -> None:
    """Drain all clients on shutdown."""
    async with _clients_lock:
        for client in _clients.values():
            await client.aclose()
        _clients.clear()
