"""Unit tests for the tools layer — all upstream HTTP is mocked via respx.

These run in <1s and cover:
  - Happy-path response parsing for every tool.
  - Cache behaviour (second call doesn't hit upstream).
  - Error mapping (upstream 5xx → UpstreamUnavailable).
  - Snapshot composition with partial failures.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from malaysia_data_mcp.application import tools
from malaysia_data_mcp.application.container import Container
from malaysia_data_mcp.domain.errors import UpstreamUnavailable
from malaysia_data_mcp.domain.models import ToolError

# =====================================================================
# Test fixtures — canned BNM/data.gov.my responses
# =====================================================================

_BNM_OPR = {
    "data": {
        "year": 2026,
        "date": "2026-05-07",
        "change_in_opr": 0,
        "new_opr_level": 2.75,
    },
    "meta": {"last_updated": "2026-05-07 15:03:15", "total_result": 1},
}

_BNM_EXCHANGE = {
    "data": [
        {
            "currency_code": "USD",
            "unit": 1,
            "rate": {
                "date": "2026-05-07",
                "buying_rate": 4.7140,
                "selling_rate": 4.7170,
                "middle_rate": 4.7155,
            },
        },
        {
            "currency_code": "SDR",
            "unit": 1,
            "rate": {
                "date": "2026-05-07",
                "buying_rate": None,  # null — must be skipped, not crash
                "selling_rate": None,
                "middle_rate": None,
            },
        },
    ]
}

_BNM_KIJANG = {
    "data": {
        "effective_date": "2026-05-07",
        "one_oz": {"buying": 18796, "selling": 19575},
        "half_oz": {"buying": 9398, "selling": 9972},
        "quarter_oz": {"buying": 4699, "selling": 5078},
    }
}

_BNM_CONSUMER_ALERT = {
    "data": [
        {
            "name": "Aurora Capital Sdn Bhd",
            "regisration_number": "",
            "added_date": "2024-03-15",
            "websites": ["aurora-capital.example"],
        },
        {
            "name": "Crown Forex Trading",
            "regisration_number": "",
            "added_date": "2023-07-01",
            "websites": [],
        },
    ]
}

_DATAGOVMY_FUEL = [
    {
        "date": "2026-05-07",
        "ron95": 4.02,
        "ron97": 4.90,
        "diesel": 5.17,
        "ron95_skps": 2.05,
        "series_type": "level",
        "ron95_budi95": 1.99,
        "diesel_eastmsia": 2.15,
    },
    {
        "date": "2026-05-07",
        "ron95": 0.05,
        "ron97": 0.0,
        "diesel": 0.05,
        "ron95_skps": 0.0,
        "series_type": "change_weekly",
        "ron95_budi95": 0.0,
        "diesel_eastmsia": 0.0,
    },
]


# =====================================================================
# Happy paths
# =====================================================================


@respx.mock
@pytest.mark.asyncio
async def test_get_overnight_policy_rate(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/opr").mock(
        return_value=httpx.Response(200, json=_BNM_OPR)
    )
    result = await tools.get_overnight_policy_rate(mock_container)
    assert result.rate_percent == 2.75
    assert result.last_change_bps == 0  # change_in_opr=0 → 0 bps


@respx.mock
@pytest.mark.asyncio
async def test_get_exchange_rates_skips_null_rates(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/exchange-rate").mock(
        return_value=httpx.Response(200, json=_BNM_EXCHANGE)
    )
    result = await tools.get_exchange_rates(mock_container)
    # SDR was null → skipped. Only USD remains.
    assert len(result.rates) == 1
    assert result.rates[0].currency_code == "USD"


@respx.mock
@pytest.mark.asyncio
async def test_get_exchange_rates_currency_filter(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/exchange-rate").mock(
        return_value=httpx.Response(200, json=_BNM_EXCHANGE)
    )
    result = await tools.get_exchange_rates(mock_container, currency="usd")
    assert len(result.rates) == 1
    assert result.rates[0].currency_code == "USD"


@respx.mock
@pytest.mark.asyncio
async def test_get_kijang_emas_per_gram_derivation(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/kijang-emas").mock(
        return_value=httpx.Response(200, json=_BNM_KIJANG)
    )
    result = await tools.get_kijang_emas_price(mock_container)
    # 19575 / 31.1034768 ≈ 629.35
    assert 629.0 <= result.per_gram_selling_myr <= 630.0


@respx.mock
@pytest.mark.asyncio
async def test_get_zakat_nisab_factual_only(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/kijang-emas").mock(
        return_value=httpx.Response(200, json=_BNM_KIJANG)
    )
    result = await tools.get_zakat_nisab_threshold(mock_container)
    assert result.nisab_85g_myr == round(result.per_gram_selling_myr * 85, 2)
    # Methodology note must mention state authorities
    assert "authority" in result.methodology_note.lower()


@respx.mock
@pytest.mark.asyncio
async def test_check_consumer_alert_substring_match(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/consumer-alert").mock(
        return_value=httpx.Response(200, json=_BNM_CONSUMER_ALERT)
    )
    result = await tools.check_consumer_alert(mock_container, query="aurora")
    assert result.found
    assert any("Aurora" in m.name for m in result.matches)
    assert "verify" in result.warning.lower()


@respx.mock
@pytest.mark.asyncio
async def test_check_consumer_alert_not_found(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/consumer-alert").mock(
        return_value=httpx.Response(200, json=_BNM_CONSUMER_ALERT)
    )
    result = await tools.check_consumer_alert(mock_container, query="zzzznotreal")
    assert not result.found
    assert result.matches == []
    # Warning still present even on not-found
    assert "verify" in result.warning.lower()


@respx.mock
@pytest.mark.asyncio
async def test_get_fuel_prices(mock_container: Container) -> None:
    respx.get("https://api.data.gov.my/data-catalogue/").mock(
        return_value=httpx.Response(200, json=_DATAGOVMY_FUEL)
    )
    result = await tools.get_fuel_prices(mock_container)
    assert result.latest.ron95_myr_per_litre == 4.02
    assert result.weekly_change_myr_per_litre["ron95"] == 0.05


# =====================================================================
# Cache behavior
# =====================================================================


@respx.mock
@pytest.mark.asyncio
async def test_cache_avoids_second_upstream_call(mock_container: Container) -> None:
    route = respx.get("https://api.bnm.gov.my/public/opr").mock(
        return_value=httpx.Response(200, json=_BNM_OPR)
    )
    await tools.get_overnight_policy_rate(mock_container)
    await tools.get_overnight_policy_rate(mock_container)
    await tools.get_overnight_policy_rate(mock_container)
    assert route.call_count == 1  # cache hit on calls 2 and 3


# =====================================================================
# Error mapping
# =====================================================================


@respx.mock
@pytest.mark.asyncio
async def test_upstream_5xx_becomes_upstream_unavailable(mock_container: Container) -> None:
    respx.get("https://api.bnm.gov.my/public/opr").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    with pytest.raises(UpstreamUnavailable):
        await tools.get_overnight_policy_rate(mock_container)


# =====================================================================
# Snapshot — partial failure semantics
# =====================================================================


@respx.mock
@pytest.mark.asyncio
async def test_snapshot_returns_tool_error_for_failed_part(mock_container: Container) -> None:
    # OPR succeeds
    respx.get("https://api.bnm.gov.my/public/opr").mock(
        return_value=httpx.Response(200, json=_BNM_OPR)
    )
    # Exchange rates succeeds
    respx.get("https://api.bnm.gov.my/public/exchange-rate").mock(
        return_value=httpx.Response(200, json=_BNM_EXCHANGE)
    )
    # Kijang Emas FAILS
    respx.get("https://api.bnm.gov.my/public/kijang-emas").mock(
        return_value=httpx.Response(503)
    )
    # Fuel succeeds
    respx.get("https://api.data.gov.my/data-catalogue/").mock(
        return_value=httpx.Response(200, json=_DATAGOVMY_FUEL)
    )

    snapshot = await tools.get_malaysia_economic_snapshot(mock_container)

    # Successful parts are real responses
    assert hasattr(snapshot.opr, "rate_percent")
    # Failed part is a ToolError, not an exception
    assert isinstance(snapshot.kijang_emas, ToolError)
    assert snapshot.kijang_emas.error_type == "upstream_unavailable"
