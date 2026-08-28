"""Pricing one gateway call from aigateway's `_aigw` accounting block.

FEATURE: per-run cost reporting (`OME-849`). aigateway publishes provider-authored cost evidence and
refuses to convert or attribute it; this module is the consumer that turns OpenRouter credits into
USD at 1:1 and decides when the evidence cannot support a price at all.

STORY: as a researcher reading a run Report, I see what my run cost — and I see an em dash rather
than a confident wrong number whenever the gateway could not observe the whole call.

Producer contract: `apps/aigateway/docs/usage-accounting.md`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from screamingface_engine.runner.accounting import (
    OPENROUTER_CREDIT_UNIT,
    PRICING_VERSION,
    accumulate,
    read_aigw,
    usd_from_aigw,
)


def _aigw(
    *,
    direct_cost_status: str = "complete",
    subtotals: Any = None,
    cache_status: str = "miss",
    attempts: Any = None,
) -> dict[str, Any]:
    """A minimal, schema-shaped `_aigw` block."""
    if subtotals is None:
        subtotals = [
            {
                "amount": "0.001",
                "unit": OPENROUTER_CREDIT_UNIT,
                "source": "openrouter.usage.cost",
            }
        ]
    return {
        "usage_accounting": {
            "schema": "aigw.chat_usage_accounting",
            "capture_status": "complete",
            "cache": {"status": cache_status, "reference": None},
            "observed_attempts": 1,
            "rendered_attempts": 1,
            "omitted_attempts": 0,
            "attempts": [_attempt()] if attempts is None else attempts,
        },
        "request_economics": {
            "schema": "aigw.request_economics",
            "observed_new_attempts": 1,
            "direct_cost_status": direct_cost_status,
            "known_direct_cost_subtotals": subtotals,
        },
    }


def _attempt(
    *,
    provider: str = "openrouter",
    response_model: str | None = "anthropic/claude-x-20260801",
    input_total: int | None = 12480,
    output_total: int | None = 742,
    cache_read: int | None = 8000,
    cache_write: int | None = 4000,
    reasoning: int | None = 610,
    outcome: str = "succeeded",
) -> dict[str, Any]:
    return {
        "schema": "aigw.provider_attempt",
        "provider": provider,
        "requested_model": "openrouter/anthropic/claude-x",
        "response_model": response_model,
        "outcome": outcome,
        "usage": {
            "status": "complete",
            "source": "provider_raw_response",
            "input": {
                "total": input_total,
                "uncached": None,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "cache_write_by_ttl": [],
            },
            "output": {"total": output_total, "reasoning": reasoning},
        },
    }


# ── the decision table (spec §3.2) ────────────────────────────────────────────────────────────


def test_a_complete_status_prices_the_single_credit_subtotal() -> None:
    assert usd_from_aigw(_aigw()) == Decimal("0.001")


def test_a_cache_hit_is_priced_at_exactly_zero() -> None:
    """INVARIANT: a cache hit genuinely cost nothing THIS request, so zero is a real claim.

    It must be `Decimal("0")` and not `None` — a dash here would hide a true saving.
    """
    priced = usd_from_aigw(
        _aigw(direct_cost_status="not_applicable", subtotals=[], cache_status="hit", attempts=[])
    )

    assert priced == Decimal("0")


def test_an_unobservable_provider_is_unpriced_not_free() -> None:
    """INVARIANT: the P0 case. `not_applicable` without a cache hit means a real billed call the
    gateway could not observe. Both this and the cache hit present an EMPTY subtotal list, so
    reading the list alone would report a paid call as free."""
    priced = usd_from_aigw(
        _aigw(direct_cost_status="not_applicable", subtotals=[], cache_status="miss", attempts=[])
    )

    assert priced is None


@pytest.mark.parametrize("status", ["partial", "unavailable", "unrecognised-future-value"])
def test_incomplete_or_unknown_statuses_are_unpriced(status: str) -> None:
    assert usd_from_aigw(_aigw(direct_cost_status=status)) is None


def test_a_missing_economics_section_is_unpriced() -> None:
    assert usd_from_aigw({"usage_accounting": {}}) is None


# ── subtotal shape ────────────────────────────────────────────────────────────────────────────


def test_an_empty_subtotal_list_under_complete_is_unpriced() -> None:
    assert usd_from_aigw(_aigw(subtotals=[])) is None


def test_several_subtotals_are_unpriced_rather_than_added() -> None:
    """INVARIANT: never add across units. Two subtotals means two currencies, and summing them
    would invent an exchange rate nobody supplied."""
    rows = [
        {"amount": "0.001", "unit": OPENROUTER_CREDIT_UNIT, "source": "s"},
        {"amount": "0.002", "unit": "some_other_credits", "source": "s"},
    ]

    assert usd_from_aigw(_aigw(subtotals=rows)) is None


def test_a_non_credits_unit_is_unpriced() -> None:
    """AIDEV-NOTE: this is what keeps the 1:1 conversion honest when a second provider appears —
    an unrecognised unit degrades instead of being treated as dollars."""
    rows = [{"amount": "0.001", "unit": "anthropic_tokens", "source": "s"}]

    assert usd_from_aigw(_aigw(subtotals=rows)) is None


# ── hostile input: the function is total and never raises ──────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [None, "", 0, [], "not-a-mapping", {"request_economics": "not-a-mapping"}],
    ids=["none", "empty-str", "int", "list", "str", "wrong-type-section"],
)
def test_malformed_accounting_is_unpriced_and_never_raises(payload: object) -> None:
    """INVARIANT: accounting must never turn a completed provider response into a run failure.

    The provider call may already be billed by the time we parse this.
    """
    assert usd_from_aigw(payload) is None


@pytest.mark.parametrize(
    "amount",
    [None, "", "abc", "-0.001", 0.001, True, "NaN", "Infinity", "1e5"],
    ids=["none", "empty", "text", "negative", "float", "bool", "nan", "inf", "exponent"],
)
def test_a_non_canonical_amount_is_refused(amount: object) -> None:
    """`float` and `bool` are refused as carriers: a float has already lost the exact JSON
    provenance, and `bool` is an `int` subclass so `True` would otherwise price as 1 credit."""
    rows = [{"amount": amount, "unit": OPENROUTER_CREDIT_UNIT, "source": "s"}]

    assert usd_from_aigw(_aigw(subtotals=rows)) is None


def test_an_amount_at_the_contract_precision_bound_survives_exactly() -> None:
    """The producer's bound is 18 integer and 33 fractional digits; nothing may be rounded."""
    amount = "1" * 18 + "." + "0" * 32 + "1"
    rows = [{"amount": amount, "unit": OPENROUTER_CREDIT_UNIT, "source": "s"}]

    assert usd_from_aigw(_aigw(subtotals=rows)) == Decimal(amount)


def test_an_explicit_zero_amount_is_priced_as_zero() -> None:
    rows = [{"amount": "0", "unit": OPENROUTER_CREDIT_UNIT, "source": "s"}]

    assert usd_from_aigw(_aigw(subtotals=rows)) == Decimal("0")


# ── the cache reference must never be priced ───────────────────────────────────────────────────


def test_a_cache_reference_never_contributes_to_the_price() -> None:
    """INVARIANT: P0. The reference describes the ORIGINAL response and is explicitly labelled
    `incurred_in_current_request: false`. Pricing it bills the researcher for a free answer."""
    payload = _aigw(
        direct_cost_status="not_applicable", subtotals=[], cache_status="hit", attempts=[]
    )
    payload["usage_accounting"]["cache"]["reference"] = {
        "kind": "cached_final_response",
        "coverage": "final_successful_response_only",
        "incurred_in_current_request": False,
        "usage": {"status": "complete", "source": "cached_converted_response"},
        "direct_cost": {
            "status": "reported",
            "amount": "9.99",
            "unit": OPENROUTER_CREDIT_UNIT,
            "source": "s",
        },
    }

    assert usd_from_aigw(payload) == Decimal("0")


# ── token and identity evidence ────────────────────────────────────────────────────────────────


def test_evidence_carries_every_token_class_and_the_authoritative_identity() -> None:
    call = read_aigw(_aigw())

    assert call is not None
    assert call.provider == "openrouter"
    assert call.response_model == "anthropic/claude-x-20260801"
    assert call.input_tokens == 12480
    assert call.output_tokens == 742
    assert call.cache_read_tokens == 8000
    assert call.cache_creation_tokens == 4000
    assert call.reasoning_tokens == 610
    assert call.cost_usd == Decimal("0.001")


def test_tokens_are_summed_across_attempts_including_failures() -> None:
    """INVARIANT: a retry genuinely costs twice, and a FAILED attempt may still carry real usage —
    the producer contract says so outright. Dropping failures under-reports the run."""
    attempts = [
        _attempt(input_total=100, output_total=10, outcome="transport_error"),
        _attempt(input_total=200, output_total=20, outcome="succeeded"),
    ]

    call = read_aigw(_aigw(attempts=attempts))

    assert call is not None
    assert call.input_tokens == 300
    assert call.output_tokens == 30


def test_the_cost_is_taken_once_from_economics_not_per_attempt() -> None:
    """aigateway already summed across attempts. Re-deriving from `attempts[]` double-counts."""
    attempts = [_attempt(), _attempt()]

    call = read_aigw(_aigw(attempts=attempts))

    assert call is not None
    assert call.cost_usd == Decimal("0.001")


def test_an_unreported_token_class_stays_none() -> None:
    call = read_aigw(_aigw(attempts=[_attempt(cache_read=None, reasoning=None)]))

    assert call is not None
    assert call.cache_read_tokens is None
    assert call.reasoning_tokens is None
    assert call.cache_creation_tokens == 4000


def test_identity_is_unavailable_when_contributing_attempts_disagree() -> None:
    """INVARIANT: summed usage cannot be attributed to one served model unless every attempt
    agrees; choosing the terminal attempt would mislabel usage from the failed attempt."""
    attempts = [
        _attempt(provider="openrouter", response_model=None, outcome="transport_error"),
        _attempt(provider="openrouter", response_model="served/by-this", outcome="succeeded"),
    ]

    call = read_aigw(_aigw(attempts=attempts))

    assert call is not None
    assert call.provider == "openrouter"
    assert call.response_model is None


def test_absent_accounting_yields_no_evidence_at_all() -> None:
    """Distinguished from "evidence that says nothing": `None` tells the caller to fall back to the
    provider's own `usage` object, which is the pre-`_aigw` behaviour."""
    assert read_aigw(None) is None
    assert read_aigw("nonsense") is None


def test_a_cache_hit_has_no_attempts_yet_is_still_priced() -> None:
    call = read_aigw(
        _aigw(direct_cost_status="not_applicable", subtotals=[], cache_status="hit", attempts=[])
    )

    assert call is not None
    assert call.cost_usd == Decimal("0")
    assert call.provider is None
    assert call.input_tokens is None


# ── the poisoning helper ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("prior", "new", "expected"),
    [
        (1, 2, 3),
        (0, 0, 0),
        (None, 2, None),
        (1, None, None),
        (None, None, None),
    ],
)
def test_accumulate_sums_known_counts_and_poisons_on_unknown(
    prior: int | None, new: int | None, expected: int | None
) -> None:
    """INVARIANT: an unknown part makes the whole unknown. A total that silently omits a part while
    presenting itself as a total is worse than no total — the same rule the producer applies to its
    own subtotals."""
    assert accumulate(prior, new) == expected


def test_accumulate_keeps_decimal_exactness() -> None:
    total = accumulate(Decimal("0.1"), Decimal("0.2"))

    assert total == Decimal("0.3")
    assert isinstance(total, Decimal)


def test_the_pricing_version_names_the_method_not_a_date() -> None:
    """AIDEV-NOTE: the version is how a future rate card coexists with this one. A consumer reads it
    to know HOW the number was reached, so it must describe the method."""
    assert PRICING_VERSION == "openrouter-credits-1usd"
