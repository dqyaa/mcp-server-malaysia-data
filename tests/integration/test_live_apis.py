"""Integration tests — hit live BNM and data.gov.my APIs.

Run with:
    pytest -m integration

Skipped by default in CI (would hit real APIs from runners). Run locally
before pushing major changes to catch upstream contract drift.
"""

from __future__ import annotations

import pytest

from malaysia_data_mcp.application import tools
from malaysia_data_mcp.application.container import Container


@pytest.fixture
async def live_container() -> Container:
    return await Container.create()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_opr() -> None:
    c = await Container.create()
    try:
        result = await tools.get_overnight_policy_rate(c)
        assert 0 < result.rate_percent < 20
        assert result.effective_date.year >= 2020
    finally:
        await c.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_exchange_rates_returns_usd() -> None:
    c = await Container.create()
    try:
        result = await tools.get_exchange_rates(c, currency="USD")
        assert len(result.rates) == 1
        usd = result.rates[0]
        assert usd.currency_code == "USD"
        # Sanity range — USD/MYR has historically been 3.5-5.0 over a decade.
        assert 3.0 <= usd.middle_rate <= 6.0
    finally:
        await c.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_kijang_emas() -> None:
    c = await Container.create()
    try:
        result = await tools.get_kijang_emas_price(c)
        # Plausibility checks — gold per gram has been > MYR 200 since ~2020
        assert result.per_gram_selling_myr > 200
        assert result.one_oz_selling_myr > result.one_oz_buying_myr
    finally:
        await c.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_fuel_prices() -> None:
    c = await Container.create()
    try:
        result = await tools.get_fuel_prices(c)
        assert 0 < result.latest.ron95_myr_per_litre < 10
        assert result.latest.ron97_myr_per_litre > result.latest.ron95_myr_per_litre
    finally:
        await c.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_consumer_alert_returns_real_data() -> None:
    c = await Container.create()
    try:
        result = await tools.check_consumer_alert(c, query="capital")
        # The BNM list has many entities containing "capital" — this should match.
        assert result.total_alert_list_size > 50
    finally:
        await c.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_snapshot_succeeds_or_partials_gracefully() -> None:
    c = await Container.create()
    try:
        result = await tools.get_malaysia_economic_snapshot(c)
        # At minimum OPR + exchange rates should always work.
        assert hasattr(result.opr, "rate_percent") or "error" in str(type(result.opr)).lower()
    finally:
        await c.aclose()
