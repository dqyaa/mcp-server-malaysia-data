"""Two-tier TTL cache: L1 (in-process) + optional L2 (Redis).

Why two-tier (interview-defensible reasoning):

- L1 (cachetools.TTLCache): nanosecond access, zero network I/O, but per-process.
  When you scale horizontally, each replica has its own cache → cache misses on
  fresh replicas, cache stampede on cold deploys.
- L2 (Redis): shared across replicas, survives process restarts, but adds ~1ms
  network hop per call. Use when you have >1 replica or need durable cache state.
- Read path: L1 → on miss → L2 → on miss → upstream. Writes populate both layers.
- Configurable: if no Redis URL is set, the L2 layer is a no-op (zero overhead).

Stampede protection: concurrent identical requests share an in-flight upstream
call via asyncio.Lock per cache key. Without this, 50 concurrent requests for
"current OPR" would all hit BNM simultaneously the first time after a cache miss.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from cachetools import TTLCache
from pydantic import BaseModel

from malaysia_data_mcp.infrastructure.observability import cache_operations_total, get_logger
from malaysia_data_mcp.infrastructure.settings import Settings

T = TypeVar("T", bound=BaseModel)

logger = get_logger(__name__)


class TwoTierCache:
    """L1 (memory) + L2 (Redis, optional) TTL cache with stampede protection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._l1: TTLCache[str, str] = TTLCache(
            maxsize=settings.cache_l1_max_size,
            ttl=settings.cache_default_ttl_seconds,
        )
        self._l2: Any | None = None  # redis.asyncio.Redis | None
        self._inflight: dict[str, asyncio.Future[str]] = {}

        if settings.cache_redis_url:
            try:
                import redis.asyncio as redis_async  # noqa: PLC0415

                self._l2 = redis_async.from_url(
                    settings.cache_redis_url,
                    decode_responses=True,
                )
                logger.info("cache_l2_enabled", url=settings.cache_redis_url)
            except ImportError:
                logger.warning("cache_l2_disabled", reason="redis package not installed")

    async def get_or_set(
        self,
        key: str,
        fetch: Callable[[], Awaitable[T]],
        model_cls: type[T],
        ttl_seconds: int | None = None,
    ) -> T:
        """Read from cache; on miss, call `fetch()`, populate both layers, return.

        Stampede-protected: concurrent calls for the same key share one upstream call.
        """
        # L1 check
        try:
            cached = self._l1[key]
            cache_operations_total.labels(layer="l1", outcome="hit").inc()
            return model_cls.model_validate_json(cached)
        except KeyError:
            cache_operations_total.labels(layer="l1", outcome="miss").inc()

        # L2 check
        if self._l2 is not None:
            try:
                cached = await self._l2.get(key)
                if cached is not None:
                    cache_operations_total.labels(layer="l2", outcome="hit").inc()
                    self._l1[key] = cached
                    return model_cls.model_validate_json(cached)
                cache_operations_total.labels(layer="l2", outcome="miss").inc()
            except Exception as exc:  # noqa: BLE001
                # L2 failure must never block the request — fall through to upstream.
                logger.warning("cache_l2_get_failed", error=str(exc), key=key)

        # Stampede protection: if another coroutine is already fetching this key,
        # wait on its future instead of issuing a parallel upstream call.
        if key in self._inflight:
            cached = await self._inflight[key]
            return model_cls.model_validate_json(cached)

        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._inflight[key] = future

        try:
            value = await fetch()
            payload = value.model_dump_json()
            await self._set(key, payload, ttl_seconds or self._settings.cache_default_ttl_seconds)
            future.set_result(payload)
            return value
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)

    async def _set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Populate both cache layers."""
        self._l1[key] = value
        cache_operations_total.labels(layer="l1", outcome="set").inc()

        if self._l2 is not None:
            try:
                await self._l2.setex(key, ttl_seconds, value)
                cache_operations_total.labels(layer="l2", outcome="set").inc()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache_l2_set_failed", error=str(exc), key=key)

    async def invalidate(self, key: str) -> None:
        """Drop a key from both layers."""
        self._l1.pop(key, None)
        if self._l2 is not None:
            try:
                await self._l2.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache_l2_delete_failed", error=str(exc), key=key)

    async def aclose(self) -> None:
        if self._l2 is not None:
            await self._l2.aclose()


# Helper for building cache keys consistently across the codebase.
def cache_key(*parts: str | int) -> str:
    """Build a colon-separated cache key. Use to ensure consistent key shape."""
    return "malaysia_data:" + ":".join(str(p) for p in parts)


def stable_hash(payload: dict[str, Any]) -> str:
    """Hash a dict into a deterministic short string for use in cache keys."""
    import hashlib  # noqa: PLC0415

    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(serialised.encode()).hexdigest()[:12]  # noqa: S324  # not security-sensitive
