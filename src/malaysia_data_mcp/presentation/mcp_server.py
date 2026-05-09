"""FastMCP server — exposes tools, resources, and prompts to MCP clients.

This is the THINNEST possible layer: it imports the pure tool functions from
application.tools and decorates them with @mcp.tool. All business logic lives
in the application layer, so this file rarely changes once written.

Run as a CLI:
    python -m malaysia_data_mcp.presentation.mcp_server         # stdio
    fastmcp dev src/malaysia_data_mcp/presentation/mcp_server.py # MCP Inspector
"""

# TODO: investigate "Unexpected non-whitespace character after JSON at position 4"
# warning observed in Claude Desktop logs during tool calls. Server functions
# correctly; suspected to be benign client-side parser noise but worth tracing.

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import Prompt

from malaysia_data_mcp.application import tools as t
from malaysia_data_mcp.application.container import get_container
from malaysia_data_mcp.application.prompts import ALL_PROMPTS
from malaysia_data_mcp.domain.errors import MalaysiaDataError
from malaysia_data_mcp.domain.models import ToolError
from malaysia_data_mcp.infrastructure.observability import (
    correlation_id,
    get_logger,
    tool_calls_total,
)

logger = get_logger(__name__)

mcp: FastMCP = FastMCP(
    "malaysia-data",
    instructions=(
        "Live access to Bank Negara Malaysia and data.gov.my datasets. "
        "Use tools for current Malaysian financial and economic data — "
        "exchange rates, OPR, gold, fuel prices, inflation, GDP, population. "
        "All data is sourced directly from official Malaysian government APIs."
    ),
)


def _serialize_error(exc: Exception) -> dict[str, Any]:
    """Convert any exception into a structured ToolError payload."""
    if isinstance(exc, MalaysiaDataError):
        err_type = type(exc).__name__
        msg = str(exc)
        upstream = getattr(exc, "upstream", None)
        retry_after = getattr(exc, "retry_after_seconds", None)
    else:
        err_type = "internal_error"
        msg = f"Unexpected: {exc}"
        upstream = None
        retry_after = None

    type_map = {
        "UpstreamTimeout": "upstream_timeout",
        "UpstreamUnavailable": "upstream_unavailable",
        "UpstreamInvalidResponse": "upstream_invalid_response",
        "RateLimitedError": "rate_limited",
        "CircuitOpenError": "circuit_open",
        "NotFoundError": "not_found",
    }
    return ToolError(
        error_type=type_map.get(err_type, "upstream_unavailable"),  # type: ignore[arg-type]
        message=msg,
        upstream=upstream,
        retry_after_seconds=retry_after,
    ).model_dump()


def _wrap(tool_name: str, func: Any) -> Any:
    """Wrap a pure tool function with MCP-friendly error handling + correlation IDs."""

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        with correlation_id() as cid:
            logger.info("tool_called", tool=tool_name, args=kwargs, correlation_id=cid)
            try:
                container = await get_container()
                result = await func(container, *args, **kwargs)
                return result.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                tool_calls_total.labels(tool=tool_name, outcome="error").inc()
                logger.warning("tool_failed", tool=tool_name, error=str(exc))
                return _serialize_error(exc)

    wrapper.__name__ = tool_name
    wrapper.__doc__ = func.__doc__
    return wrapper


# =====================================================================
# Register all 15 tools with FastMCP
# =====================================================================


@mcp.tool()
async def get_exchange_rates(currency: str | None = None) -> dict[str, Any]:
    """Latest BNM interbank exchange rates.

    Args:
        currency: Optional ISO code filter (e.g. 'USD', 'SGD'). None = all currencies.

    Returns: ExchangeRatesResponse with buying, selling, and middle rates.
    """
    return await _wrap("get_exchange_rates", t.get_exchange_rates)(currency=currency)


@mcp.tool()
async def get_overnight_policy_rate() -> dict[str, Any]:
    """Current Overnight Policy Rate (OPR) from BNM Monetary Policy Committee."""
    return await _wrap("get_overnight_policy_rate", t.get_overnight_policy_rate)()


@mcp.tool()
async def get_base_rates() -> dict[str, Any]:
    """Base rates and Base Lending Rates (BLR) by Malaysian bank."""
    return await _wrap("get_base_rates", t.get_base_rates)()


@mcp.tool()
async def get_interbank_rates() -> dict[str, Any]:
    """Conventional Malaysian interbank money market rates by tenure."""
    return await _wrap("get_interbank_rates", t.get_interbank_rates)()


@mcp.tool()
async def get_islamic_interbank_rate() -> dict[str, Any]:
    """Islamic Interbank Money Market (IIMM) rates by tenure."""
    return await _wrap("get_islamic_interbank_rate", t.get_islamic_interbank_rate)()


@mcp.tool()
async def get_kijang_emas_price() -> dict[str, Any]:
    """Live BNM Kijang Emas gold prices (1oz, 1/2oz, 1/4oz) plus per-gram derivation."""
    return await _wrap("get_kijang_emas_price", t.get_kijang_emas_price)()


@mcp.tool()
async def check_consumer_alert(query: str) -> dict[str, Any]:
    """Check if an entity name appears on BNM's unauthorised entities list.

    Args:
        query: Company or platform name to search for (case-insensitive substring match).

    Note: Absence from list does NOT prove authorisation. Always verify with BNM.
    """
    return await _wrap("check_consumer_alert", t.check_consumer_alert)(query=query)


@mcp.tool()
async def get_usd_myr_reference_rate() -> dict[str, Any]:
    """KL USD/MYR Reference Rate, published daily at 3:30pm KL time by BNM."""
    return await _wrap("get_usd_myr_reference_rate", t.get_usd_myr_reference_rate)()


@mcp.tool()
async def get_fuel_prices() -> dict[str, Any]:
    """Latest weekly RON95, RON97, and Diesel prices in Malaysia."""
    return await _wrap("get_fuel_prices", t.get_fuel_prices)()


@mcp.tool()
async def get_cpi_inflation() -> dict[str, Any]:
    """Latest CPI index and year-on-year inflation rate (monthly)."""
    return await _wrap("get_cpi_inflation", t.get_cpi_inflation)()


@mcp.tool()
async def get_gdp_data() -> dict[str, Any]:
    """Latest quarterly real GDP growth (year-on-year)."""
    return await _wrap("get_gdp_data", t.get_gdp_data)()


@mcp.tool()
async def get_population_stats(state: str = "Malaysia") -> dict[str, Any]:
    """Latest population estimate. Pass a state name or 'Malaysia' for national."""
    return await _wrap("get_population_stats", t.get_population_stats)(state=state)


@mcp.tool()
async def get_household_income(state: str = "Malaysia") -> dict[str, Any]:
    """Latest median and mean household income, optionally by state."""
    return await _wrap("get_household_income", t.get_household_income)(state=state)


@mcp.tool()
async def get_zakat_nisab_threshold() -> dict[str, Any]:
    """Today's gold-standard nisab threshold in MYR (85g × Kijang Emas selling).

    FACTUAL ONLY — does not interpret fiqh or compute zakat owed. Consult your
    state zakat authority (PPZ-MAIWP, LZS, JAWHAR, etc.) for binding rulings.
    """
    return await _wrap("get_zakat_nisab_threshold", t.get_zakat_nisab_threshold)()


@mcp.tool()
async def get_malaysia_economic_snapshot() -> dict[str, Any]:
    """One-call composite snapshot: OPR + USD/MYR + gold + fuel + inflation."""
    return await _wrap("get_malaysia_economic_snapshot", t.get_malaysia_economic_snapshot)()


# =====================================================================
# Resources — read-only addressable data
# =====================================================================


@mcp.resource("bnm://exchange-rate/{currency}")
async def exchange_rate_resource(currency: str) -> str:
    """Single-currency exchange rate as an MCP resource.

    URIs like `bnm://exchange-rate/USD` are addressable, cacheable, and let
    the host display them in a sidebar without invoking a tool.
    """
    container = await get_container()
    try:
        resp = await t.get_exchange_rates(container, currency=currency.upper())
        return resp.model_dump_json(indent=2)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(_serialize_error(exc), indent=2)


@mcp.resource("bnm://opr/current")
async def opr_resource() -> str:
    """Current OPR as a resource."""
    container = await get_container()
    try:
        resp = await t.get_overnight_policy_rate(container)
        return resp.model_dump_json(indent=2)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(_serialize_error(exc), indent=2)


@mcp.resource("malaysia://snapshot/economic")
async def snapshot_resource() -> str:
    """Composite economic snapshot as a resource."""
    container = await get_container()
    resp = await t.get_malaysia_economic_snapshot(container)
    return resp.model_dump_json(indent=2)


@mcp.resource("malaysia://datasets/index")
def datasets_index() -> str:
    """List of all data sources this server exposes — metadata only, no API calls."""
    return json.dumps(
        {
            "bnm": [
                "exchange-rate",
                "opr",
                "base-rate",
                "interest-rate",
                "islamic-interbank-rate",
                "kijang-emas",
                "consumer-alert",
                "kl-usd-reference-rate",
            ],
            "datagovmy": [
                "fuelprice",
                "consumerprice",
                "gdp_real_supply",
                "population_state",
                "hh_income_state",
            ],
            "derived": ["zakat_nisab_threshold", "economic_snapshot"],
        },
        indent=2,
    )


# =====================================================================
# Prompts — slash-command templates the host can surface
# =====================================================================


# =====================================================================
# Prompts — slash-command templates the host can surface
# =====================================================================


@mcp.prompt()
def economic_briefing(audience: str = "general public") -> str:
    """Generate a Malaysia economic briefing using live BNM and DOSM data."""
    return ALL_PROMPTS[0].template.format(audience=audience)


@mcp.prompt()
def scam_check(entity_name: str) -> str:
    """Check whether a financial entity is on Bank Negara's unauthorised list."""
    return ALL_PROMPTS[1].template.format(entity_name=entity_name)


@mcp.prompt()
def currency_planner(currency: str, amount_myr: str) -> str:
    """Plan a foreign currency conversion using BNM rates."""
    return ALL_PROMPTS[2].template.format(currency=currency, amount_myr=amount_myr)


# =====================================================================
# Entry point
# =====================================================================


def main() -> None:
    """CLI entry point — runs the server over stdio."""
    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)
    finally:
        # Ensure container resources are drained on exit.
        async def _drain() -> None:
            from malaysia_data_mcp.application.container import (  # noqa: PLC0415
                _global_container,
            )
            if _global_container is not None:
                await _global_container.aclose()

        try:
            asyncio.run(_drain())
        except RuntimeError:
            pass  # event loop already closed


if __name__ == "__main__":
    main()
