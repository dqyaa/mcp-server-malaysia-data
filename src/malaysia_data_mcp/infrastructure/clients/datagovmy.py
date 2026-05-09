"""data.gov.my OpenAPI client.

Endpoint pattern: GET https://api.data.gov.my/data-catalogue/?id={dataset_id}
Returns a JSON array of records sorted by date.
No authentication required.

Dataset IDs we use:
  fuelprice                — weekly fuel prices
  cpi_2010 / consumerprice — monthly CPI; field names vary by version
  gdp_real_supply          — quarterly GDP at constant prices
  population               — annual state population
  hh_income_state          — annual median/mean household income by state
"""

from __future__ import annotations

from datetime import UTC, date as Date
from datetime import UTC, datetime
from typing import Any

from malaysia_data_mcp.domain.errors import NotFoundError, UpstreamInvalidResponse
from malaysia_data_mcp.domain.models import (
    CPIResponse,
    FuelPricesResponse,
    FuelPriceWeek,
    GDPResponse,
    HouseholdIncomeResponse,
    PopulationStatsResponse,
)
from malaysia_data_mcp.infrastructure.http import ResilientHTTPClient


class DataGovMyClient:
    """Typed wrapper over data.gov.my dataset API."""

    def __init__(self, http: ResilientHTTPClient, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    async def _query(self, dataset_id: str, params: dict[str, Any] | None = None) -> list[Any]:
        """All data.gov.my calls — returns the records list."""
        merged = {"id": dataset_id, **(params or {})}
        url = f"{self._base_url}/data-catalogue/"
        result = await self._http.get_json(url, params=merged)
        if not isinstance(result, list):
            raise UpstreamInvalidResponse(
                f"data.gov.my returned non-list payload for {dataset_id}",
                upstream="datagovmy",
            )
        return result

    # -----------------------------------------------------------------
    # Fuel prices
    # -----------------------------------------------------------------
    async def fuel_prices(self) -> FuelPricesResponse:
        # Sort descending by date, take 4 records: latest 'level', latest 'change_weekly',
        # previous 'level' (for sanity).
        records = await self._query(
            "fuelprice", {"limit": 8, "sort": "-date"}
        )
        try:
            level_records = [r for r in records if r.get("series_type") == "level"]
            change_records = [r for r in records if r.get("series_type") == "change_weekly"]

            if not level_records:
                raise UpstreamInvalidResponse(
                    "No 'level' fuel price records returned", upstream="datagovmy"
                )

            latest = level_records[0]
            latest_week = FuelPriceWeek(
                week_starting=Date.fromisoformat(latest["date"]),
                ron95_myr_per_litre=latest["ron95"],
                ron97_myr_per_litre=latest["ron97"],
                diesel_myr_per_litre=latest["diesel"],
                ron95_budi95_myr_per_litre=latest.get("ron95_budi95"),
                diesel_east_malaysia_myr_per_litre=latest.get("diesel_eastmsia"),
            )

            change = change_records[0] if change_records else {}
            change_dict = {
                "ron95": float(change.get("ron95") or 0.0),
                "ron97": float(change.get("ron97") or 0.0),
                "diesel": float(change.get("diesel") or 0.0),
            }
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"data.gov.my fuelprice response shape unexpected: {exc}",
                upstream="datagovmy",
            ) from exc

        return FuelPricesResponse(
            latest=latest_week,
            weekly_change_myr_per_litre=change_dict,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    # -----------------------------------------------------------------
    # CPI / inflation
    # -----------------------------------------------------------------
    async def cpi(self) -> CPIResponse:
        # data.gov.my dataset is `cpi_headline`. Each record is one (date, division)
        # tuple; we want division='overall' for the headline figure.
        records = await self._query(
            "cpi_headline", {"limit": 13, "sort": "-date"}  # 13 to ensure we get y-o-y pair
        )
        if not records:
            raise UpstreamInvalidResponse("No CPI records returned", upstream="datagovmy")

        try:
            overall = [r for r in records if r.get("division") == "overall"]
            if not overall:
                raise UpstreamInvalidResponse(
                    "No 'overall' division in CPI response", upstream="datagovmy"
                )
            latest = overall[0]
            # y-o-y: same month last year. Records sorted desc; index 12 if present.
            yoy_record = overall[12] if len(overall) > 12 else None
            yoy_pct = (
                ((latest["index"] - yoy_record["index"]) / yoy_record["index"]) * 100
                if yoy_record
                else 0.0
            )
            return CPIResponse(
                period=latest["date"][:7],
                cpi_index=float(latest["index"]),
                inflation_yoy_percent=round(yoy_pct, 2),
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"CPI response shape unexpected: {exc}", upstream="datagovmy"
            ) from exc

    # -----------------------------------------------------------------
    # GDP
    # -----------------------------------------------------------------
    async def gdp(self) -> GDPResponse:
        # 2026 dataset name is `gdp_qtr_real`. Each date has 3 records (series:
        # growth_yoy / growth_qoq / abs). Pull enough rows to capture the latest
        # quarter's full triplet.
        records = await self._query(
            "gdp_qtr_real", {"limit": 12, "sort": "-date"}
        )
        if not records:
            raise UpstreamInvalidResponse("No GDP records", upstream="datagovmy")
        try:
            latest_date = records[0]["date"]
            growth = next(
                (r for r in records if r["date"] == latest_date and r.get("series") == "growth_yoy"),
                None,
            )
            abs_val = next(
                (r for r in records if r["date"] == latest_date and r.get("series") == "abs"),
                None,
            )
            if growth is None:
                raise UpstreamInvalidResponse(
                    "No growth_yoy series in GDP response", upstream="datagovmy"
                )
            d = Date.fromisoformat(latest_date)
            quarter = (d.month - 1) // 3 + 1
            return GDPResponse(
                period=f"{d.year}-Q{quarter}",
                gdp_growth_yoy_percent=float(growth["value"]),
                gdp_real_million_myr=float(abs_val["value"]) if abs_val else None,
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"GDP response shape unexpected: {exc}", upstream="datagovmy"
            ) from exc

    # -----------------------------------------------------------------
    # Population
    # -----------------------------------------------------------------
    async def population(self, state: str = "Malaysia") -> PopulationStatsResponse:
        # data.gov.my doesn't honour state-filter on the population_state dataset
        # consistently. Pull the latest year's records and filter ourselves.
        # Each (state, age, sex, ethnicity) combination is a row; we want the
        # 'overall_age' / 'overall_sex' / 'overall_ethnicity' totals.
        records = await self._query(
            "population_state", {"limit": 5000, "sort": "-date"}
        )
        if not records:
            raise NotFoundError("No population data returned")
        target = state.strip().lower()
        for r in records:
            if (
                str(r.get("state", "")).lower() == target
                and r.get("age") == "overall_age"
                and r.get("sex") == "overall_sex"
                and r.get("ethnicity") == "overall_ethnicity"
            ):
                d = Date.fromisoformat(r["date"])
                return PopulationStatsResponse(
                    state=r["state"],
                    year=d.year,
                    population_thousands=float(r["population"]),
                    fetched_at=datetime.now(UTC).replace(tzinfo=None),
                )
        raise NotFoundError(f"No population data found for state '{state}'")

    # -----------------------------------------------------------------
    # Household Income
    # -----------------------------------------------------------------
    async def household_income(self, state: str = "Malaysia") -> HouseholdIncomeResponse:
        # Same pattern as population: server-side state filter is unreliable.
        records = await self._query(
            "hh_income_state", {"limit": 200, "sort": "-date"}
        )
        if not records:
            raise NotFoundError("No household income data returned")
        target = state.strip().lower()
        for r in records:
            if str(r.get("state", "")).lower() == target:
                d = Date.fromisoformat(r["date"])
                return HouseholdIncomeResponse(
                    state=r["state"],
                    year=d.year,
                    median_income_myr=float(r["income_median"]),
                    mean_income_myr=float(r["income_mean"]),
                    fetched_at=datetime.now(UTC).replace(tzinfo=None),
                )
        raise NotFoundError(f"No household income data found for state '{state}'")
