"""Domain models — typed responses for every tool.

Why Pydantic v2 here (interview-defensible reasoning):

1. Schema validation at the API boundary catches upstream contract changes
   immediately, not three layers deep in the call stack.

2. FastMCP auto-generates JSON Schema for MCP tool inputs/outputs from these
   models, giving the LLM client (Claude Desktop, Cursor, LangGraph) precise
   type info — which directly improves tool-call accuracy.

3. Pydantic v2 is ~5-50x faster than v1 (Rust core via pydantic-core),
   meaningful when an agent calls 10+ tools in a single conversation turn.

4. Tests can construct fixture objects without hitting the network, and
   round-trip through `model_dump_json()` for snapshot tests.

5. `Field(...)` descriptions become tool documentation that the LLM reads.
   This is non-negotiable: a tool with a vague schema gets called wrong.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# =====================================================================
# Common
# =====================================================================


class _BaseResponse(BaseModel):
    """Base for all tool responses. Sets strict config and adds metadata."""

    model_config = ConfigDict(
        # Reject unknown fields — catches upstream API additions early.
        extra="forbid",
        # Validate on assignment too, not just construction.
        validate_assignment=True,
        # Use enum values when serialising.
        use_enum_values=True,
    )


# Reusable type aliases — improve readability and central place to refine constraints.
Percent = Annotated[float, Field(ge=-100, le=100, description="Percentage value.")]
Bps = Annotated[
    float,
    Field(ge=-1000, le=1000, description="Basis points (100 bps = 1%)."),
]
PositiveAmount = Annotated[float, Field(ge=0, description="Non-negative MYR amount.")]


# =====================================================================
# Errors
# =====================================================================


class ToolError(BaseModel):
    """Returned when an upstream API call fails. Tools never raise into MCP transport.

    Why this matters: if a tool raises an unhandled exception, the MCP client
    gets a generic protocol error and the agent loses context about *why* the
    call failed. Returning a typed error lets the model retry intelligently
    or explain the failure to the user.
    """

    error: bool = True
    error_type: Literal[
        "upstream_unavailable",
        "upstream_timeout",
        "upstream_invalid_response",
        "rate_limited",
        "circuit_open",
        "validation_error",
        "not_found",
    ]
    message: str
    upstream: str | None = Field(
        None, description="Which upstream service failed (e.g. 'bnm-openapi')."
    )
    retry_after_seconds: float | None = Field(
        None, description="Hint for caller; populated for rate_limited / circuit_open."
    )


# =====================================================================
# 1. BNM: Exchange Rates
# =====================================================================


class ExchangeRate(_BaseResponse):
    currency_code: str = Field(..., description="ISO 4217 code, e.g. 'USD', 'SGD', 'JPY'.")
    unit: int = Field(..., description="Currency unit (typically 1; JPY/IDR are 100).")
    date: Date = Field(..., description="Effective trading date.")
    buying_rate: float = Field(
        ..., description="MYR received per `unit` foreign currency when selling to a bank."
    )
    selling_rate: float = Field(
        ..., description="MYR paid per `unit` foreign currency when buying from a bank."
    )
    middle_rate: float = Field(..., description="Average of buying and selling rates.")


class ExchangeRatesResponse(_BaseResponse):
    """Latest BNM interbank exchange rates."""

    rates: list[ExchangeRate]
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/exchange-rate"


# =====================================================================
# 2. BNM: Overnight Policy Rate
# =====================================================================


class OPRResponse(_BaseResponse):
    """Current Overnight Policy Rate set by BNM Monetary Policy Committee."""

    rate_percent: Percent = Field(..., description="Current OPR level in percent.")
    effective_date: Date = Field(..., description="Date this OPR level took effect.")
    last_change_bps: Bps = Field(
        ..., description="Most recent change in basis points (0 = held; +25 = +0.25pp)."
    )
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/opr"


# =====================================================================
# 3. BNM: Base Rates and Base Lending Rates
# =====================================================================


class BankBaseRate(_BaseResponse):
    bank_name: str
    base_rate_percent: Percent
    base_lending_rate_percent: Percent | None = None
    indicative_effective_lending_rate_percent: Percent | None = None
    effective_date: Date | None = None


class BaseRatesResponse(_BaseResponse):
    """Base rates and BLR/BFR by bank (latest)."""

    banks: list[BankBaseRate]
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/base-rate"


# =====================================================================
# 4. BNM: Interbank Rates
# =====================================================================


class InterbankRate(_BaseResponse):
    tenure: str = Field(..., description="e.g. 'overnight', '1-week', '1-month', '3-month'.")
    rate_percent: Percent
    volume_million_myr: float | None = None
    effective_date: Date


class InterbankRatesResponse(_BaseResponse):
    rates: list[InterbankRate]
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/interest-rate"


# =====================================================================
# 5. BNM: Islamic Interbank Rates
# =====================================================================


class IslamicInterbankRatesResponse(_BaseResponse):
    """IIMM (Islamic Interbank Money Market) rates by tenure."""

    rates: list[InterbankRate]
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/islamic-interbank-rate"


# =====================================================================
# 6. BNM: Kijang Emas (gold)
# =====================================================================


class KijangEmasResponse(_BaseResponse):
    """Live Kijang Emas gold prices from BNM.

    NOTE: We compute per-gram price from 1 oz selling price. We do NOT provide
    zakat advisory output — see ADR-0004. The 85g nisab threshold reflects the
    gold-standard methodology used by most Malaysian state authorities, but
    users should verify with their state's zakat body (PPZ, LZS, etc.).
    """

    effective_date: Date
    one_oz_buying_myr: PositiveAmount
    one_oz_selling_myr: PositiveAmount
    half_oz_buying_myr: PositiveAmount
    half_oz_selling_myr: PositiveAmount
    quarter_oz_buying_myr: PositiveAmount
    quarter_oz_selling_myr: PositiveAmount
    per_gram_selling_myr: PositiveAmount = Field(
        ..., description="Derived: 1oz selling / 31.1035g (troy oz)."
    )
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/kijang-emas"


# =====================================================================
# 7. BNM: Consumer Alert
# =====================================================================


class ConsumerAlertEntity(_BaseResponse):
    name: str
    registration_number: str = ""
    added_date: Date | None = None
    websites: list[str] = Field(default_factory=list)


class ConsumerAlertResponse(_BaseResponse):
    """Result of checking a name against BNM's unauthorised entities list."""

    query: str = Field(..., description="The name searched for.")
    found: bool = Field(..., description="True if any matching entity is on the list.")
    matches: list[ConsumerAlertEntity] = Field(
        default_factory=list,
        description="All entities whose name contains the query (case-insensitive).",
    )
    total_alert_list_size: int
    warning: str = (
        "Absence from this list does NOT mean the entity is authorised. Always "
        "verify directly with BNM at https://www.bnm.gov.my/financial-consumer-alert-list "
        "before transacting."
    )
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/consumer-alert"


# =====================================================================
# 8. BNM: USD/MYR Reference Rate
# =====================================================================


class USDMYRReferenceRateResponse(_BaseResponse):
    """KL USD/MYR Reference Rate — published daily at 3:30pm by BNM.

    Computed from weighted-average volume of interbank USD/MYR FX spot
    transactions by domestic financial institutions.
    """

    date: Date
    rate: float = Field(..., description="USD/MYR reference rate (1 USD = X MYR).")
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — /public/kl-usd-reference-rate"


# =====================================================================
# 9. data.gov.my: Fuel Prices
# =====================================================================


class FuelPriceWeek(_BaseResponse):
    week_starting: Date
    ron95_myr_per_litre: float = Field(..., description="Standard subsidised RON95 (peninsula).")
    ron97_myr_per_litre: float = Field(..., description="RON97 premium, market-priced.")
    diesel_myr_per_litre: float = Field(..., description="Standard diesel (peninsula).")
    ron95_budi95_myr_per_litre: float | None = Field(
        None,
        description="BUDI95 unsubsidised RON95 (introduced 2025 for non-eligible groups).",
    )
    diesel_east_malaysia_myr_per_litre: float | None = Field(
        None, description="Subsidised diesel rate for Sabah, Sarawak, Labuan."
    )


class FuelPricesResponse(_BaseResponse):
    latest: FuelPriceWeek
    weekly_change_myr_per_litre: dict[str, float] = Field(
        ..., description="Change vs previous week, per fuel grade."
    )
    fetched_at: datetime
    source: str = "data.gov.my — fuelprice"


# =====================================================================
# 10. data.gov.my: CPI / Inflation
# =====================================================================


class CPIResponse(_BaseResponse):
    """Latest CPI and y-o-y inflation rate."""

    period: str = Field(..., description="YYYY-MM of the latest reading.")
    cpi_index: float = Field(..., description="CPI index value (base year per DOSM methodology).")
    inflation_yoy_percent: Percent = Field(..., description="Year-on-year change in CPI, percent.")
    fetched_at: datetime
    source: str = "data.gov.my — cpi_2010 / consumerprice"


# =====================================================================
# 11. data.gov.my: GDP
# =====================================================================


class GDPResponse(_BaseResponse):
    """Latest quarterly GDP growth (constant prices)."""

    period: str = Field(..., description="YYYY-Qn of the latest reading.")
    gdp_growth_yoy_percent: Percent = Field(..., description="Real GDP growth, year-on-year.")
    gdp_real_million_myr: float | None = Field(None, description="Real GDP value in MYR million.")
    fetched_at: datetime
    source: str = "data.gov.my — gdp_real_supply"


# =====================================================================
# 12. data.gov.my: Population
# =====================================================================


class PopulationStatsResponse(_BaseResponse):
    """Latest national or state population estimate."""

    state: str = Field(..., description="'Malaysia' for national, or state name.")
    year: int
    population_thousands: float
    fetched_at: datetime
    source: str = "data.gov.my / OpenDOSM — population"


# =====================================================================
# 13. data.gov.my: Household Income
# =====================================================================


class HouseholdIncomeResponse(_BaseResponse):
    """Latest median and mean household income, optionally by state."""

    state: str
    year: int
    median_income_myr: PositiveAmount
    mean_income_myr: PositiveAmount
    fetched_at: datetime
    source: str = "data.gov.my — hh_income_state"


# =====================================================================
# 14. Derived: Zakat Nisab Threshold (factual, not advisory)
# =====================================================================


class ZakatNisabResponse(_BaseResponse):
    """Today's gold-standard nisab threshold in MYR.

    DELIBERATELY FACTUAL: this returns the live MYR value of 85g of gold using
    BNM's Kijang Emas selling price. It does NOT compute zakat owed, classify
    asset eligibility, or interpret fiqh. State authorities (PPZ-MAIWP, LZS,
    JAWHAR, etc.) maintain their own methodology — users should consult them.
    See ADR-0004 for the rationale on excluding advisory output.
    """

    effective_date: Date
    per_gram_selling_myr: PositiveAmount
    nisab_85g_myr: PositiveAmount = Field(
        ..., description="85 grams × per-gram selling price."
    )
    methodology_note: str = (
        "85g gold standard is widely used by Malaysian state authorities. "
        "Some methodologies use silver (595g) which yields a lower threshold. "
        "Consult your state zakat authority for the binding figure."
    )
    fetched_at: datetime
    source: str = "Bank Negara Malaysia OpenAPI — derived from /public/kijang-emas"


# =====================================================================
# 15. Composite: Economic Snapshot
# =====================================================================


class EconomicSnapshotResponse(_BaseResponse):
    """One-call comprehensive snapshot: rates, prices, indicators.

    Composes 5 underlying tools. Useful for single-request agent workflows
    where the user asks "give me an economic overview of Malaysia."
    """

    opr: OPRResponse | ToolError
    usd_myr: ExchangeRate | ToolError
    kijang_emas: KijangEmasResponse | ToolError
    fuel_prices: FuelPricesResponse | ToolError
    inflation: CPIResponse | ToolError
    fetched_at: datetime
    source: str = "Composite — see individual sources within each field."

    @field_validator("fetched_at", mode="before")
    @classmethod
    def _strip_tz(cls, v: datetime | str) -> datetime:
        # Accept either tz-aware or naive; downstream consumers expect naive UTC.
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v.replace(tzinfo=None) if v.tzinfo else v
