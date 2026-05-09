"""Lightweight dependency injection container.

Why a container instead of just module-level globals: the container can be
constructed with overrides for tests (fake HTTP clients, ephemeral cache),
which is the foundation of fast, deterministic unit tests. Production code
asks the container for its dependencies; tests construct a container with
test doubles. No global state, no monkey-patching.

This is a hand-rolled minimal container — we don't pull in `dependency-injector`
because the framework's surface area would dwarf our actual needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from malaysia_data_mcp.infrastructure.cache import TwoTierCache
from malaysia_data_mcp.infrastructure.clients.bnm import BNMClient
from malaysia_data_mcp.infrastructure.clients.datagovmy import DataGovMyClient
from malaysia_data_mcp.infrastructure.http import (
    ResilientHTTPClient,
    close_all_clients,
    get_or_create_client,
)
from malaysia_data_mcp.infrastructure.observability import (
    configure_logging,
    configure_tracing,
    get_logger,
)
from malaysia_data_mcp.infrastructure.settings import Settings, get_settings

logger = get_logger(__name__)


@dataclass
class Container:
    """All long-lived dependencies. One instance per process."""

    settings: Settings
    cache: TwoTierCache
    bnm: BNMClient
    datagovmy: DataGovMyClient
    _http_clients: list[ResilientHTTPClient] = field(default_factory=list)

    async def aclose(self) -> None:
        """Drain HTTP clients and close cache. Call on shutdown."""
        await self.cache.aclose()
        await close_all_clients()

    @classmethod
    async def create(cls, settings: Settings | None = None) -> "Container":
        """Build the container from real dependencies.

        Tests should call `Container(...)` directly with mocks.
        """
        s = settings or get_settings()
        configure_logging(s)
        configure_tracing(s)

        bnm_http = await get_or_create_client(s, "bnm", s.bnm_rate_limit_per_minute)
        datagovmy_http = await get_or_create_client(
            s, "datagovmy", s.datagovmy_rate_limit_per_minute
        )

        container = cls(
            settings=s,
            cache=TwoTierCache(s),
            bnm=BNMClient(bnm_http, s.bnm_base_url),
            datagovmy=DataGovMyClient(datagovmy_http, s.datagovmy_base_url),
            _http_clients=[bnm_http, datagovmy_http],
        )
        logger.info(
            "container_initialised",
            environment=s.environment,
            otel_enabled=s.otel_enabled,
            cache_l2=bool(s.cache_redis_url),
        )
        return container


# Module-level singleton for the running server. Tests should NOT use this.
_global_container: Container | None = None


async def get_container() -> Container:
    global _global_container
    if _global_container is None:
        _global_container = await Container.create()
    return _global_container


def set_container(container: Any) -> None:
    """Test helper — inject a custom container."""
    global _global_container
    _global_container = container


def clear_container() -> None:
    global _global_container
    _global_container = None
