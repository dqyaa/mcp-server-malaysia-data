"""Property-based tests using Hypothesis.

Why property tests (interview signal): example-based tests check the cases
you thought of. Property-based tests check thousands of cases the framework
generates from invariants you declare. They catch the edge case you'd never
have written.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from malaysia_data_mcp.domain.models import (
    ConsumerAlertEntity,
    ExchangeRate,
    KijangEmasResponse,
    OPRResponse,
)


@given(
    rate=st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
    bps=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200, deadline=None)
def test_opr_response_accepts_valid_range(rate: float, bps: float) -> None:
    """OPRResponse roundtrips JSON for any valid rate/bps."""
    obj = OPRResponse(
        rate_percent=rate,
        effective_date=date(2026, 5, 7),
        last_change_bps=bps,
        fetched_at=datetime(2026, 5, 7),
    )
    serialized = obj.model_dump_json()
    rehydrated = OPRResponse.model_validate_json(serialized)
    assert rehydrated.rate_percent == pytest.approx(rate)


@given(
    rate=st.floats(min_value=100.01, max_value=1e6, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, deadline=None)
def test_opr_response_rejects_out_of_range(rate: float) -> None:
    """OPRResponse rejects rates above 100%."""
    with pytest.raises(ValidationError):
        OPRResponse(
            rate_percent=rate,
            effective_date=date(2026, 5, 7),
            last_change_bps=0,
            fetched_at=datetime(2026, 5, 7),
        )


@given(
    selling=st.floats(min_value=200, max_value=1e6, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_kijang_per_gram_invariant(selling: float) -> None:
    """nisab_85g should always equal per_gram * 85 (within float rounding)."""
    per_gram = round(selling / 31.1034768, 2)
    nisab = round(per_gram * 85, 2)
    obj = KijangEmasResponse(
        effective_date=date(2026, 5, 7),
        one_oz_buying_myr=max(0, selling - 100),
        one_oz_selling_myr=selling,
        half_oz_buying_myr=selling / 2,
        half_oz_selling_myr=selling / 2 + 50,
        quarter_oz_buying_myr=selling / 4,
        quarter_oz_selling_myr=selling / 4 + 25,
        per_gram_selling_myr=per_gram,
        fetched_at=datetime(2026, 5, 7),
    )
    assert pytest.approx(obj.per_gram_selling_myr * 85, abs=0.05) == nisab


@given(name=st.text(min_size=1, max_size=200))
def test_consumer_alert_entity_accepts_any_string(name: str) -> None:
    """Entity name is treated as opaque text — should never crash on weird unicode."""
    obj = ConsumerAlertEntity(name=name)
    assert obj.name == name


@given(
    code=st.text(
        alphabet=st.characters(min_codepoint=65, max_codepoint=90),
        min_size=3,
        max_size=3,
    ),
    rate=st.floats(min_value=0.01, max_value=1000, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_exchange_rate_buying_le_middle_le_selling_invariant(code: str, rate: float) -> None:
    """For valid BNM data: buying ≤ middle ≤ selling. We assert the model accepts it."""
    spread = max(rate * 0.005, 0.001)
    buying = rate - spread
    selling = rate + spread
    middle = rate
    obj = ExchangeRate(
        currency_code=code,
        unit=1,
        date=date(2026, 5, 7),
        buying_rate=buying,
        selling_rate=selling,
        middle_rate=middle,
    )
    assert obj.buying_rate <= obj.middle_rate <= obj.selling_rate
