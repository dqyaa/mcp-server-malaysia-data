"""Quickstart: tests every tool against live BNM and data.gov.my APIs.

Run with:
    pip install -e .
    python quickstart.py

Output: each tool's name, status (✓/✗), and a one-line summary of the result.

This is the script you run to convince yourself (or a reviewer) that the
server actually works against real APIs in <30 seconds.
"""

from __future__ import annotations

import asyncio
import sys

from malaysia_data_mcp.application.container import Container
from malaysia_data_mcp.application import tools


async def main() -> int:
    print("Initialising container...")
    c = await Container.create()

    cases: list[tuple[str, callable]] = [
        ("get_overnight_policy_rate", lambda: tools.get_overnight_policy_rate(c)),
        ("get_exchange_rates(USD)", lambda: tools.get_exchange_rates(c, currency="USD")),
        ("get_kijang_emas_price", lambda: tools.get_kijang_emas_price(c)),
        ("get_zakat_nisab_threshold", lambda: tools.get_zakat_nisab_threshold(c)),
        ("get_fuel_prices", lambda: tools.get_fuel_prices(c)),
        ("check_consumer_alert(capital)", lambda: tools.check_consumer_alert(c, query="capital")),
        ("get_usd_myr_reference_rate", lambda: tools.get_usd_myr_reference_rate(c)),
        ("get_cpi_inflation", lambda: tools.get_cpi_inflation(c)),
        ("get_base_rates", lambda: tools.get_base_rates(c)),
        ("get_interbank_rates", lambda: tools.get_interbank_rates(c)),
        ("get_islamic_interbank_rate", lambda: tools.get_islamic_interbank_rate(c)),
        ("get_gdp_data", lambda: tools.get_gdp_data(c)),
        ("get_population_stats(Selangor)", lambda: tools.get_population_stats(c, state="Selangor")),
        ("get_household_income(Selangor)", lambda: tools.get_household_income(c, state="Selangor")),
        ("get_malaysia_economic_snapshot", lambda: tools.get_malaysia_economic_snapshot(c)),
    ]

    passed = 0
    failed = 0

    print(f"\n{'Tool':40s}  {'Result'}")
    print("-" * 80)
    for name, fn in cases:
        try:
            result = await fn()
            summary = _summarise(result)
            print(f"  ✓ {name:38s}  {summary}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {name:38s}  {type(exc).__name__}: {str(exc)[:60]}")
            failed += 1

    print("-" * 80)
    print(f"\n{passed}/{len(cases)} tools functional.")
    await c.aclose()
    return 0 if failed == 0 else 1


def _summarise(result: object) -> str:
    """Produce a one-line preview of the response."""
    cls = type(result).__name__
    if hasattr(result, "rate_percent"):
        return f"{cls}: rate={result.rate_percent}%"  # type: ignore[attr-defined]
    # InterbankRate-list responses (no `currency_code` on items)
    if cls in ("InterbankRatesResponse", "IslamicInterbankRatesResponse"):
        rates = result.rates  # type: ignore[attr-defined]
        if rates:
            return f"{cls}: {len(rates)} tenures, e.g. {rates[0].tenure}={rates[0].rate_percent}%"
        return f"{cls}: empty"
    if hasattr(result, "rates") and isinstance(result.rates, list) and result.rates:  # type: ignore[attr-defined]
        first = result.rates[0]  # type: ignore[attr-defined]
        return f"{cls}: {first.currency_code}={first.middle_rate}"
    if hasattr(result, "per_gram_selling_myr"):
        return f"{cls}: gold/g=RM {result.per_gram_selling_myr}"  # type: ignore[attr-defined]
    if hasattr(result, "nisab_85g_myr"):
        return f"{cls}: nisab=RM {result.nisab_85g_myr}"  # type: ignore[attr-defined]
    if hasattr(result, "latest"):
        latest = result.latest  # type: ignore[attr-defined]
        return f"{cls}: RON95=RM {latest.ron95_myr_per_litre}, RON97=RM {latest.ron97_myr_per_litre}"
    if hasattr(result, "found"):
        return (
            f"{cls}: found={result.found}, "  # type: ignore[attr-defined]
            f"matches={len(result.matches)}/"  # type: ignore[attr-defined]
            f"{result.total_alert_list_size}"  # type: ignore[attr-defined]
        )
    if hasattr(result, "rate") and hasattr(result, "date"):
        return f"{cls}: rate={result.rate} on {result.date}"  # type: ignore[attr-defined]
    if hasattr(result, "cpi_index"):
        return f"{cls}: CPI={result.cpi_index}, y/y={result.inflation_yoy_percent}%"  # type: ignore[attr-defined]
    if hasattr(result, "banks"):
        return f"{cls}: {len(result.banks)} banks"  # type: ignore[attr-defined]
    if hasattr(result, "median_income_myr"):
        return (
            f"{cls}: median=RM {result.median_income_myr}, "  # type: ignore[attr-defined]
            f"mean=RM {result.mean_income_myr}"  # type: ignore[attr-defined]
        )
    if hasattr(result, "population_thousands"):
        return f"{cls}: {result.state} = {result.population_thousands}k"  # type: ignore[attr-defined]
    if hasattr(result, "gdp_growth_yoy_percent"):
        return f"{cls}: GDP y/y = {result.gdp_growth_yoy_percent}%"  # type: ignore[attr-defined]
    if hasattr(result, "opr") and hasattr(result, "fuel_prices"):
        return f"{cls}: composite of 5 sub-tools"
    return f"{cls}"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
