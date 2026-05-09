"""Bank Negara Malaysia OpenAPI client.

All BNM endpoints are versioned via Accept header: `application/vnd.BNM.API.v1+json`.
No authentication required. Free tier is generous (no published QPS limit but
we self-throttle at 60/min to be a good citizen).

Endpoint reference: https://apikijangportal.bnm.gov.my/openapi
"""

from __future__ import annotations

from datetime import UTC, date as Date
from datetime import UTC, datetime
from typing import Any

from malaysia_data_mcp.domain.errors import UpstreamInvalidResponse
from malaysia_data_mcp.domain.models import (
    BankBaseRate,
    BaseRatesResponse,
    ConsumerAlertEntity,
    ConsumerAlertResponse,
    ExchangeRate,
    ExchangeRatesResponse,
    InterbankRate,
    InterbankRatesResponse,
    IslamicInterbankRatesResponse,
    KijangEmasResponse,
    OPRResponse,
    USDMYRReferenceRateResponse,
)
from malaysia_data_mcp.infrastructure.http import ResilientHTTPClient

# BNM uses a versioned media type — ALWAYS send this header.
BNM_ACCEPT = "application/vnd.BNM.API.v1+json"

# Troy ounce → grams conversion for Kijang Emas per-gram derivation.
TROY_OZ_GRAMS = 31.1034768


class BNMClient:
    """Typed wrapper over BNM's public OpenAPI."""

    def __init__(self, http: ResilientHTTPClient, base_url: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")

    async def _get(self, path: str) -> Any:
        """All BNM calls go through here; consistent Accept header + base URL."""
        return await self._http.get_json(f"{self._base_url}{path}", accept=BNM_ACCEPT)

    # -----------------------------------------------------------------
    # 1. Exchange Rates
    # -----------------------------------------------------------------
    async def exchange_rates(self) -> ExchangeRatesResponse:
        raw = await self._get("/exchange-rate")
        try:
            data = raw["data"]
            rates = []
            for r in data:
                rate_data = r.get("rate", {})
                # Some currencies (e.g. SDR) occasionally return null rates;
                # skip rather than fail the whole response.
                if (
                    rate_data.get("buying_rate") is None
                    or rate_data.get("selling_rate") is None
                    or rate_data.get("middle_rate") is None
                ):
                    continue
                rates.append(
                    ExchangeRate(
                        currency_code=r["currency_code"],
                        unit=r["unit"],
                        date=Date.fromisoformat(rate_data["date"]),
                        buying_rate=rate_data["buying_rate"],
                        selling_rate=rate_data["selling_rate"],
                        middle_rate=rate_data["middle_rate"],
                    )
                )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM exchange-rate response shape unexpected: {exc}",
                upstream="bnm",
            ) from exc
        return ExchangeRatesResponse(rates=rates, fetched_at=datetime.now(UTC).replace(tzinfo=None))

    # -----------------------------------------------------------------
    # 2. Overnight Policy Rate
    # -----------------------------------------------------------------
    async def opr(self) -> OPRResponse:
        raw = await self._get("/opr")
        try:
            data = raw["data"]
            return OPRResponse(
                rate_percent=data["new_opr_level"],
                effective_date=Date.fromisoformat(data["date"]),
                last_change_bps=float(data["change_in_opr"]) * 100,  # API gives % → bps
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM opr response shape unexpected: {exc}", upstream="bnm"
            ) from exc

    # -----------------------------------------------------------------
    # 3. Base Rates / BLR
    # -----------------------------------------------------------------
    async def base_rates(self) -> BaseRatesResponse:
        raw = await self._get("/base-rate")
        try:
            data = raw["data"]
            banks = [
                BankBaseRate(
                    bank_name=b.get("bank_name", b.get("name", "")),
                    base_rate_percent=b.get("base_rate", 0.0),
                    base_lending_rate_percent=b.get("blr") or b.get("base_lending_rate"),
                    indicative_effective_lending_rate_percent=b.get(
                        "indicative_effective_lending_rate"
                    ),
                    effective_date=(
                        Date.fromisoformat(b["effective_date"])
                        if b.get("effective_date")
                        else None
                    ),
                )
                for b in data
            ]
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM base-rate response shape unexpected: {exc}", upstream="bnm"
            ) from exc
        return BaseRatesResponse(banks=banks, fetched_at=datetime.now(UTC).replace(tzinfo=None))

    # -----------------------------------------------------------------
    # 4. Interbank Rates
    # -----------------------------------------------------------------
    async def interbank_rates(self) -> InterbankRatesResponse:
        raw = await self._get("/interest-rate")
        rates = self._parse_interbank(raw)
        return InterbankRatesResponse(rates=rates, fetched_at=datetime.now(UTC).replace(tzinfo=None))

    # -----------------------------------------------------------------
    # 5. Islamic Interbank Rates
    # -----------------------------------------------------------------
    async def islamic_interbank_rates(self) -> IslamicInterbankRatesResponse:
        raw = await self._get("/islamic-interbank-rate")
        rates = self._parse_interbank(raw)
        return IslamicInterbankRatesResponse(rates=rates, fetched_at=datetime.now(UTC).replace(tzinfo=None))

    @staticmethod
    def _parse_interbank(raw: Any) -> list[InterbankRate]:
        """BNM returns wide-format rows: each record has columns for each tenure.

        Example: {"product": "interbank", "date": "2026-05-07", "overnight": 2.76,
                  "1_week": 2.85, "1_month": null, ...}

        We pivot into long-format InterbankRate rows, picking the 'interbank'
        product (or 'overall' if 'interbank' is absent), and dropping null tenures.
        """
        try:
            data = raw["data"]
            if isinstance(data, dict):
                data = [data]

            # Prefer 'interbank' product, fall back to 'overall', then any record.
            preferred = next(
                (r for r in data if r.get("product") == "interbank"),
                None,
            )
            if preferred is None:
                preferred = next(
                    (r for r in data if r.get("product") == "overall"),
                    data[0] if data else None,
                )
            if preferred is None:
                return []

            effective_date = Date.fromisoformat(preferred["date"])
            tenure_cols = [
                "overnight",
                "1_week",
                "1_month",
                "3_month",
                "6_month",
                "1_year",
            ]
            rates = []
            for col in tenure_cols:
                value = preferred.get(col)
                if value is None:
                    continue
                rates.append(
                    InterbankRate(
                        tenure=col.replace("_", "-"),
                        rate_percent=float(value),
                        volume_million_myr=None,
                        effective_date=effective_date,
                    )
                )
            return rates
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM interbank response shape unexpected: {exc}", upstream="bnm"
            ) from exc

    # -----------------------------------------------------------------
    # 6. Kijang Emas (gold)
    # -----------------------------------------------------------------
    async def kijang_emas(self) -> KijangEmasResponse:
        raw = await self._get("/kijang-emas")
        try:
            data = raw["data"]
            one_oz_sell = float(data["one_oz"]["selling"])
            return KijangEmasResponse(
                effective_date=Date.fromisoformat(data["effective_date"]),
                one_oz_buying_myr=float(data["one_oz"]["buying"]),
                one_oz_selling_myr=one_oz_sell,
                half_oz_buying_myr=float(data["half_oz"]["buying"]),
                half_oz_selling_myr=float(data["half_oz"]["selling"]),
                quarter_oz_buying_myr=float(data["quarter_oz"]["buying"]),
                quarter_oz_selling_myr=float(data["quarter_oz"]["selling"]),
                per_gram_selling_myr=round(one_oz_sell / TROY_OZ_GRAMS, 2),
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM kijang-emas response shape unexpected: {exc}", upstream="bnm"
            ) from exc

    # -----------------------------------------------------------------
    # 7. Consumer Alert
    # -----------------------------------------------------------------
    async def consumer_alert(self, query: str) -> ConsumerAlertResponse:
        raw = await self._get("/consumer-alert")
        try:
            data = raw["data"]
            q_lower = query.lower().strip()
            entities = [
                ConsumerAlertEntity(
                    name=e["name"],
                    # BNM has a typo in the field name: "regisration_number"
                    registration_number=e.get("regisration_number") or e.get("registration_number") or "",
                    added_date=(
                        Date.fromisoformat(e["added_date"])
                        if e.get("added_date")
                        else None
                    ),
                    websites=e.get("websites") or [],
                )
                for e in data
            ]
            matches = [e for e in entities if q_lower in e.name.lower()]
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM consumer-alert response shape unexpected: {exc}", upstream="bnm"
            ) from exc

        return ConsumerAlertResponse(
            query=query,
            found=len(matches) > 0,
            matches=matches[:25],  # Cap to avoid overwhelming an LLM context
            total_alert_list_size=len(entities),
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    # -----------------------------------------------------------------
    # 8. KL USD/MYR Reference Rate
    # -----------------------------------------------------------------
    async def usd_myr_reference_rate(self) -> USDMYRReferenceRateResponse:
        raw = await self._get("/kl-usd-reference-rate")
        try:
            data = raw["data"]
            return USDMYRReferenceRateResponse(
                date=Date.fromisoformat(data["date"]),
                rate=float(data["rate"]),
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise UpstreamInvalidResponse(
                f"BNM kl-usd-reference-rate response shape unexpected: {exc}",
                upstream="bnm",
            ) from exc
