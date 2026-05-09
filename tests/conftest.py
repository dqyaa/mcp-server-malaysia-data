"""Shared pytest fixtures.

Notable fixtures:
  test_settings    — Settings overridden for tests (no Redis, low retries).
  fake_http        — A ResilientHTTPClient backed by respx mock router.
  mock_container   — A Container wired with mocked HTTP clients.
  live_container   — A real container hitting BNM/data.gov.my (integration only).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import respx

from malaysia_data_mcp.application.container import Container
from malaysia_data_mcp.infrastructure.cache import TwoTierCache
from malaysia_data_mcp.infrastructure.clients.bnm import BNMClient
from malaysia_data_mcp.infrastructure.clients.datagovmy import DataGovMyClient
from malaysia_data_mcp.infrastructure.http import ResilientHTTPClient
from malaysia_data_mcp.infrastructure.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Settings tuned for fast deterministic tests."""
    return Settings(
        environment="dev",
        http_timeout_seconds=2.0,
        http_max_retries=0,  # no retries in unit tests; we test retry separately
        cache_default_ttl_seconds=60,
        cache_l1_max_size=64,
        cache_redis_url=None,
        log_level="WARNING",
        log_json=False,
        otel_enabled=False,
        metrics_enabled=False,
        bnm_rate_limit_per_minute=10000,
        datagovmy_rate_limit_per_minute=10000,
    )


@pytest_asyncio.fixture
async def respx_mock() -> AsyncIterator[respx.MockRouter]:
    """A respx router that intercepts httpx calls for the duration of a test."""
    async with respx.mock(assert_all_called=False) as router:
        yield router


@pytest_asyncio.fixture
async def fake_bnm_http(test_settings: Settings) -> AsyncIterator[ResilientHTTPClient]:
    client = ResilientHTTPClient(test_settings, "bnm", 10000)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def fake_datagovmy_http(test_settings: Settings) -> AsyncIterator[ResilientHTTPClient]:
    client = ResilientHTTPClient(test_settings, "datagovmy", 10000)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def mock_container(
    test_settings: Settings,
    fake_bnm_http: ResilientHTTPClient,
    fake_datagovmy_http: ResilientHTTPClient,
) -> AsyncIterator[Container]:
    """A test-isolated Container — no real HTTP, no Redis."""
    cache = TwoTierCache(test_settings)
    container = Container(
        settings=test_settings,
        cache=cache,
        bnm=BNMClient(fake_bnm_http, test_settings.bnm_base_url),
        datagovmy=DataGovMyClient(fake_datagovmy_http, test_settings.datagovmy_base_url),
    )
    yield container
    await container.aclose()
