"""Contract tests — validate upstream APIs still return the shape we expect.

Run daily in CI (separate workflow) so we know within 24h if BNM or data.gov.my
silently changes their response. This is the test that catches "everything was
fine yesterday, why is the snapshot returning nulls today?"
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.contract
@pytest.mark.asyncio
async def test_bnm_opr_contract() -> None:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            "https://api.bnm.gov.my/public/opr",
            headers={"Accept": "application/vnd.BNM.API.v1+json"},
            timeout=15,
        )
    assert r.status_code == 200
    data = r.json()
    assert "data" in data
    record = data["data"]
    # Required shape — if BNM removes any of these, our parser dies.
    assert "new_opr_level" in record
    assert "date" in record
    assert "change_in_opr" in record


@pytest.mark.contract
@pytest.mark.asyncio
async def test_bnm_exchange_rate_contract() -> None:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            "https://api.bnm.gov.my/public/exchange-rate",
            headers={"Accept": "application/vnd.BNM.API.v1+json"},
            timeout=15,
        )
    assert r.status_code == 200
    data = r.json()
    assert "data" in data
    assert isinstance(data["data"], list)
    if data["data"]:
        first = data["data"][0]
        assert "currency_code" in first
        assert "unit" in first
        assert "rate" in first
        assert "date" in first["rate"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_bnm_kijang_emas_contract() -> None:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            "https://api.bnm.gov.my/public/kijang-emas",
            headers={"Accept": "application/vnd.BNM.API.v1+json"},
            timeout=15,
        )
    assert r.status_code == 200
    data = r.json()["data"]
    for k in ("one_oz", "half_oz", "quarter_oz", "effective_date"):
        assert k in data, f"Kijang Emas response missing '{k}'"
    for size in ("one_oz", "half_oz", "quarter_oz"):
        assert "buying" in data[size]
        assert "selling" in data[size]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_datagovmy_fuel_contract() -> None:
    async with httpx.AsyncClient(follow_redirects=True) as c:
        r = await c.get(
            "https://api.data.gov.my/data-catalogue/",
            params={"id": "fuelprice", "limit": 4, "sort": "-date"},
            timeout=15,
        )
    assert r.status_code == 200
    records = r.json()
    assert isinstance(records, list)
    if records:
        first = records[0]
        for k in ("date", "ron95", "ron97", "diesel", "series_type"):
            assert k in first, f"Fuel record missing '{k}'"
