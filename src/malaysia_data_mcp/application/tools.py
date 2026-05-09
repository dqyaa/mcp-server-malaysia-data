"""Pure tool functions — the core business logic.

Critical design choice: this module knows NOTHING about MCP. Tools are async
functions returning Pydantic models. The MCP server (presentation layer) wraps
them with the @mcp.tool decorator. The REST server wraps them as FastAPI routes.
The LangGraph agent imports them directly.

This separation means:
- We can unit-test every tool without spinning up an MCP server.
- We can expose the same logic via 3 transports (MCP / REST / direct import)
  without duplicating business logic.
- A reviewer reading this file sees the *behaviour* of the system without
  protocol noise.
"""

from __future__ import annotations

from datetime import UTC, datetime

from malaysia_data_mcp.application.container import Container
from malaysia_data_mcp.domain.errors import MalaysiaDataError, NotFoundError
from malaysia_data_mcp.domain.models import (
    BaseRatesResponse,
    ConsumerAlertResponse,
    CPIResponse,
    EconomicSnapshotResponse,
    ExchangeRate,
    ExchangeRatesResponse,
    FuelPricesResponse,
    GDPResponse,
    HouseholdIncomeResponse,
    InterbankRatesResponse,
    IslamicInterbankRatesResponse,
    KijangEmasResponse,
    OPRResponse,
    PopulationStatsResponse,
    ToolError,
    USDMYRReferenceRateResponse,
    ZakatNisabResponse,
)
from malaysia_data_mcp.infrastructure.cache import cache_key, stable_hash
from malaysia_data_mcp.infrastructure.observability import (
    get_logger,
    tool_call_duration,
    tool_calls_total,
)

logger = get_logger(__name__)

# Per-tool TTLs (seconds). Set by data freshness profile.
TTL_FAST = 60          # exchange rates change intraday
TTL_MEDIUM = 3600      # OPR changes ~6x/year
TTL_SLOW = 86400       # fuel prices change weekly
TTL_VERY_SLOW = 604800 # population, GDP — annual/quarterly


# =====================================================================
# Tool 1: Exchange Rates
# =====================================================================


async def get_exchange_rates(c: Container, currency: str | None = None) -> ExchangeRatesResponse:
    """Latest BNM interbank exchange rates (MYR vs major currencies).

    Args:
        currency: Optional ISO code filter ('USD', 'SGD'). None = all currencies.
    """
    import time  # noqa: PLC0415

    started = time.perf_counter()
    try:
        key = cache_key("exchange_rates", "all")
        result = await c.cache.get_or_set(
            key, c.bnm.exchange_rates, ExchangeRatesResponse, ttl_seconds=TTL_FAST
        )
        if currency:
            filtered = [r for r in result.rates if r.currency_code.upper() == currency.upper()]
            if not filtered:
                raise NotFoundError(f"Currency '{currency}' not in BNM dataset")
            result = ExchangeRatesResponse(
                rates=filtered, fetched_at=result.fetched_at, source=result.source
            )
        tool_calls_total.labels(tool="get_exchange_rates", outcome="success").inc()
        return result
    finally:
        tool_call_duration.labels(tool="get_exchange_rates").observe(time.perf_counter() - started)


# =====================================================================
# Tool 2: OPR
# =====================================================================


async def get_overnight_policy_rate(c: Container) -> OPRResponse:
    """Current Overnight Policy Rate set by BNM Monetary Policy Committee."""
    return await c.cache.get_or_set(
        cache_key("opr"), c.bnm.opr, OPRResponse, ttl_seconds=TTL_MEDIUM
    )


# =====================================================================
# Tool 3: Base Rates / BLR
# =====================================================================


async def get_base_rates(c: Container) -> BaseRatesResponse:
    """Base rates and BLR/BFR by bank — used to estimate retail loan rates."""
    return await c.cache.get_or_set(
        cache_key("base_rates"), c.bnm.base_rates, BaseRatesResponse, ttl_seconds=TTL_MEDIUM
    )


# =====================================================================
# Tool 4: Interbank Rates
# =====================================================================


async def get_interbank_rates(c: Container) -> InterbankRatesResponse:
    """Conventional interbank money market rates by tenure."""
    return await c.cache.get_or_set(
        cache_key("interbank"),
        c.bnm.interbank_rates,
        InterbankRatesResponse,
        ttl_seconds=TTL_FAST,
    )


# =====================================================================
# Tool 5: Islamic Interbank Rates
# =====================================================================


async def get_islamic_interbank_rate(c: Container) -> IslamicInterbankRatesResponse:
    """Islamic Interbank Money Market (IIMM) rates."""
    return await c.cache.get_or_set(
        cache_key("iimm"),
        c.bnm.islamic_interbank_rates,
        IslamicInterbankRatesResponse,
        ttl_seconds=TTL_FAST,
    )


# =====================================================================
# Tool 6: Kijang Emas
# =====================================================================


async def get_kijang_emas_price(c: Container) -> KijangEmasResponse:
    """Live Kijang Emas gold price + per-gram derivation. Factual only."""
    return await c.cache.get_or_set(
        cache_key("kijang_emas"),
        c.bnm.kijang_emas,
        KijangEmasResponse,
        ttl_seconds=TTL_FAST,
    )


# =====================================================================
# Tool 7: Consumer Alert
# =====================================================================


async def check_consumer_alert(c: Container, query: str) -> ConsumerAlertResponse:
    """Check whether an entity name appears on BNM's unauthorised list.

    IMPORTANT: absence from this list is NOT proof of authorisation. Always
    verify directly with BNM before transacting with any financial entity.
    """
    if not query.strip():
        raise NotFoundError("Empty query")
    # Cache the full alert list (tens of MB → minimal); filter in-process.
    key = cache_key("consumer_alert", stable_hash({"query": query.lower()}))

    async def _fetch() -> ConsumerAlertResponse:
        return await c.bnm.consumer_alert(query)

    return await c.cache.get_or_set(
        key, _fetch, ConsumerAlertResponse, ttl_seconds=TTL_SLOW
    )


# =====================================================================
# Tool 8: USD/MYR reference rate
# =====================================================================


async def get_usd_myr_reference_rate(c: Container) -> USDMYRReferenceRateResponse:
    """KL USD/MYR Reference Rate, published daily at 3:30pm KL time."""
    return await c.cache.get_or_set(
        cache_key("usd_myr_ref"),
        c.bnm.usd_myr_reference_rate,
        USDMYRReferenceRateResponse,
        ttl_seconds=TTL_FAST,
    )


# =====================================================================
# Tool 9: Fuel Prices
# =====================================================================


async def get_fuel_prices(c: Container) -> FuelPricesResponse:
    """Latest weekly fuel prices (RON95, RON97, Diesel) and week-on-week change."""
    return await c.cache.get_or_set(
        cache_key("fuel_prices"),
        c.datagovmy.fuel_prices,
        FuelPricesResponse,
        ttl_seconds=TTL_SLOW,
    )


# =====================================================================
# Tool 10: CPI / Inflation
# =====================================================================


async def get_cpi_inflation(c: Container) -> CPIResponse:
    """Latest CPI index and year-on-year inflation rate (monthly)."""
    return await c.cache.get_or_set(
        cache_key("cpi"), c.datagovmy.cpi, CPIResponse, ttl_seconds=TTL_SLOW
    )


# =====================================================================
# Tool 11: GDP
# =====================================================================


async def get_gdp_data(c: Container) -> GDPResponse:
    """Latest quarterly real GDP growth (year-on-year)."""
    return await c.cache.get_or_set(
        cache_key("gdp"), c.datagovmy.gdp, GDPResponse, ttl_seconds=TTL_VERY_SLOW
    )


# =====================================================================
# Tool 12: Population
# =====================================================================


async def get_population_stats(c: Container, state: str = "Malaysia") -> PopulationStatsResponse:
    """Latest population estimate, nationally or by state.

    Args:
        state: 'Malaysia' or a Malaysian state name (e.g. 'Selangor', 'Pulau Pinang').
    """
    key = cache_key("population", state.lower())

    async def _fetch() -> PopulationStatsResponse:
        return await c.datagovmy.population(state)

    return await c.cache.get_or_set(key, _fetch, PopulationStatsResponse, ttl_seconds=TTL_VERY_SLOW)


# =====================================================================
# Tool 13: Household Income
# =====================================================================


async def get_household_income(
    c: Container, state: str = "Malaysia"
) -> HouseholdIncomeResponse:
    """Latest median and mean household income by state."""
    key = cache_key("household_income", state.lower())

    async def _fetch() -> HouseholdIncomeResponse:
        return await c.datagovmy.household_income(state)

    return await c.cache.get_or_set(
        key, _fetch, HouseholdIncomeResponse, ttl_seconds=TTL_VERY_SLOW
    )


# =====================================================================
# Tool 14: Zakat Nisab Threshold (factual)
# =====================================================================


async def get_zakat_nisab_threshold(c: Container) -> ZakatNisabResponse:
    """Today's gold-standard nisab threshold in MYR (85g × Kijang Emas selling).

    This tool is factual only: it does NOT compute zakat owed, classify asset
    eligibility, or interpret fiqh. State authorities maintain their own
    methodology — consult PPZ-MAIWP, LZS, JAWHAR, or your relevant authority.
    """
    gold = await get_kijang_emas_price(c)
    nisab = round(gold.per_gram_selling_myr * 85, 2)
    return ZakatNisabResponse(
        effective_date=gold.effective_date,
        per_gram_selling_myr=gold.per_gram_selling_myr,
        nisab_85g_myr=nisab,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


# =====================================================================
# Tool 15: Composite Economic Snapshot
# =====================================================================


async def get_malaysia_economic_snapshot(c: Container) -> EconomicSnapshotResponse:
    """One-call snapshot of Malaysia's key economic indicators.

    Composes: OPR, USD/MYR, Kijang Emas, fuel prices, inflation. Each sub-call
    is independently fault-tolerant — if one fails, its slot returns a ToolError
    rather than failing the whole snapshot.
    """
    import asyncio  # noqa: PLC0415

    async def _safe(coro: object, label: str) -> object:
        try:
            return await coro  # type: ignore[misc]
        except MalaysiaDataError as exc:
            logger.warning("snapshot_partial_failure", part=label, error=str(exc))
            return ToolError(
                error_type="upstream_unavailable",
                message=str(exc),
                upstream=label,
            )

    async def _usd_myr() -> ExchangeRate | ToolError:
        try:
            rates = await get_exchange_rates(c, currency="USD")
            return rates.rates[0]
        except MalaysiaDataError as exc:
            return ToolError(
                error_type="upstream_unavailable", message=str(exc), upstream="bnm"
            )

    opr_t, usd_t, gold_t, fuel_t, cpi_t = await asyncio.gather(
        _safe(get_overnight_policy_rate(c), "opr"),
        _usd_myr(),
        _safe(get_kijang_emas_price(c), "kijang_emas"),
        _safe(get_fuel_prices(c), "fuel_prices"),
        _safe(get_cpi_inflation(c), "cpi"),
    )

    return EconomicSnapshotResponse(
        opr=opr_t,  # type: ignore[arg-type]
        usd_myr=usd_t,
        kijang_emas=gold_t,  # type: ignore[arg-type]
        fuel_prices=fuel_t,  # type: ignore[arg-type]
        inflation=cpi_t,  # type: ignore[arg-type]
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


# =====================================================================
# Registry — central list for the MCP/REST presentation layers.
# =====================================================================

ALL_TOOLS = {
    "get_exchange_rates": get_exchange_rates,
    "get_overnight_policy_rate": get_overnight_policy_rate,
    "get_base_rates": get_base_rates,
    "get_interbank_rates": get_interbank_rates,
    "get_islamic_interbank_rate": get_islamic_interbank_rate,
    "get_kijang_emas_price": get_kijang_emas_price,
    "check_consumer_alert": check_consumer_alert,
    "get_usd_myr_reference_rate": get_usd_myr_reference_rate,
    "get_fuel_prices": get_fuel_prices,
    "get_cpi_inflation": get_cpi_inflation,
    "get_gdp_data": get_gdp_data,
    "get_population_stats": get_population_stats,
    "get_household_income": get_household_income,
    "get_zakat_nisab_threshold": get_zakat_nisab_threshold,
    "get_malaysia_economic_snapshot": get_malaysia_economic_snapshot,
}
