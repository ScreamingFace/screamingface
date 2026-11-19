from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aigateway.core.credits import CreditAmount


@pytest.mark.parametrize(
    "value",
    [
        {"status": "available", "as_of": datetime.now(UTC)},
        {"status": "stale", "amount_usd": "1"},
        {"status": "unavailable", "amount_usd": "0"},
        {"status": "unlimited", "amount_usd": "10", "as_of": datetime.now(UTC)},
        {"status": "available", "amount_usd": "1", "as_of": datetime(2026, 11, 11)},
        {"status": "available", "amount_usd": "NaN", "as_of": datetime.now(UTC)},
        {"status": "available", "amount_usd": "Infinity", "as_of": datetime.now(UTC)},
    ],
)
def test_amounts_cannot_contradict_availability_or_omit_observation_time(value):
    with pytest.raises(ValidationError):
        CreditAmount.model_validate(value)


def test_exact_zero_is_distinct_from_unknown():
    zero = CreditAmount(status="available", amount_usd=Decimal("0"), as_of=datetime.now(UTC))
    unknown = CreditAmount(status="unavailable", reason="lookup_failed")
    assert zero.amount_usd == 0 and zero.status == "available"
    assert unknown.amount_usd is None and unknown.status == "unavailable"
