"""Run-level saved cost: the avoided-cost reader and its two accumulators (PRD E3/E5, tests 3/5/16).

FEATURE: run-level saved cost (PRD ans:Q2). The gateway stores what a cached response originally
cost; on a hit the engine reads it and totals it SEPARATELY from the run's own spend.
STORY: as an operator I see what the run's cache hits avoided, with the coverage that makes a
partial total auditable — and I never see the two provenances collapsed into one number.

INVARIANT (I1): a hit's CURRENT-request cost is 0. The avoided amount is a counterfactual and is
reported on its own field. Reading it into `usd_from_aigw` would bill a free answer.

INVARIANT (S7/M8): `reported` money and `archive_matched` money live in two accumulators and are
never summed. This file asserts there is no third accumulator.
"""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest

from screamingface_engine.runner.cache_counters import (
    SAVED_COST_ARCHIVE_HITS,
    SAVED_COST_ARCHIVE_USD,
    SAVED_COST_REPORTED_HITS,
    SAVED_COST_UNPRICED_HITS,
    SAVED_COST_USD,
    RunCacheCounters,
)
from screamingface_engine.world.accounting import (
    OPENROUTER_CREDIT_UNIT,
    AvoidedCost,
    avoided_usd_for_outcome,
    avoided_usd_from_aigw,
    usd_from_aigw,
)
from screamingface_engine.world.cache_readback import CacheOutcome


def _aigw(*, direct_cost: dict[str, Any] | None, cache_status: str = "hit") -> dict[str, Any]:
    """A minimal, schema-shaped `_aigw` block with a cache reference."""
    reference: dict[str, Any] | None = None
    if direct_cost is not None:
        reference = {
            "kind": "cached_final_response",
            "coverage": "final_successful_response_only",
            "incurred_in_current_request": False,
            "usage": {"status": "complete", "source": "cached_converted_response"},
            "direct_cost": direct_cost,
        }
    return {
        "usage_accounting": {
            "schema": "aigw.chat_usage_accounting",
            "capture_status": "complete",
            "cache": {"status": cache_status, "reference": reference},
            "observed_attempts": 0,
            "rendered_attempts": 0,
            "omitted_attempts": 0,
            "attempts": [],
        },
        "request_economics": {
            "schema": "aigw.request_economics",
            "observed_new_attempts": 0,
            "direct_cost_status": "not_applicable",
            "known_direct_cost_subtotals": [],
        },
    }


# ── the pair invariant: both halves or neither ─────────────────────────────────────────────────


def test_an_avoided_cost_carries_both_halves_or_neither() -> None:
    # INVARIANT: `provenance` is `None` if and only if `usd` is. A lone amount cannot say which
    # claim it makes, and a lone provenance names a claim with no amount behind it.
    with pytest.raises(ValueError):
        AvoidedCost(usd=Decimal("0"), provenance=None)
    with pytest.raises(ValueError):
        AvoidedCost(usd=None, provenance="reported")

    assert AvoidedCost() == AvoidedCost(usd=None, provenance=None)
    assert AvoidedCost(usd=Decimal("0.5"), provenance="archive_matched").usd == Decimal("0.5")


# ── test 3: the hit's current-request cost stays 0; the saving is separate ─────────────────────


def test_a_hit_reports_its_avoided_cost_without_pricing_the_current_request() -> None:
    # I1: the SAME block yields both answers. `usd_from_aigw` prices THIS request at exactly zero;
    # `avoided_usd_from_aigw` reads the stored cost the reference carries. Collapsing them would
    # bill the researcher for an answer the cache served.
    payload = _aigw(
        direct_cost={
            "status": "reported",
            "amount": "9.99",
            "unit": OPENROUTER_CREDIT_UNIT,
            "source": "openrouter.usage.cost",
        }
    )

    assert usd_from_aigw(payload) == Decimal("0")
    assert avoided_usd_from_aigw(payload) == AvoidedCost(usd=Decimal("9.99"), provenance="reported")


def test_openrouter_credits_convert_one_to_one() -> None:
    payload = _aigw(
        direct_cost={"status": "reported", "amount": "0.0125", "unit": OPENROUTER_CREDIT_UNIT}
    )

    assert avoided_usd_from_aigw(payload).usd == Decimal("0.0125")


def test_a_usd_reference_is_already_dollars() -> None:
    # The v5 archive-paired rows store `unit: "usd"`, so no rate applies — and the provenance is
    # `archive_matched`, never `reported`.
    payload = _aigw(direct_cost={"status": "archive_matched", "amount": "0.25", "unit": "usd"})

    assert avoided_usd_from_aigw(payload) == AvoidedCost(
        usd=Decimal("0.25"), provenance="archive_matched"
    )


@pytest.mark.parametrize(
    "direct_cost",
    [
        None,
        {"status": "unavailable", "amount": None, "unit": None, "source": None},
        {"status": "absent", "amount": None, "unit": None, "source": None},
        {"status": "unit_unknown", "amount": "1", "unit": None, "source": "s"},
        {"status": "reported", "amount": "1", "unit": "anthropic_tokens", "source": "s"},
        {"status": "reported", "amount": "1", "source": "s"},
        {"status": "archive_matched", "amount": "-1", "unit": "usd"},
    ],
    ids=[
        "no-reference",
        "unavailable",
        "absent",
        "unit-unknown",
        "unknown-unit",
        "reported-without-a-unit",
        "negative-archive-amount",
    ],
)
def test_anything_unpriceable_is_an_empty_avoided_cost(direct_cost: dict[str, Any] | None) -> None:
    # S14: never guess a rate, and never a negative saving. An unpriced hit enters no total; the
    # counters record it as coverage instead.
    assert avoided_usd_from_aigw(_aigw(direct_cost=direct_cost)) == AvoidedCost()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "",
        0,
        [],
        "not-a-mapping",
        {"usage_accounting": "not-a-mapping"},
        {"usage_accounting": {"cache": []}},
    ],
    ids=["none", "empty-str", "int", "list", "str", "wrong-type-section", "wrong-type-cache"],
)
def test_malformed_accounting_is_empty_and_never_raises(payload: object) -> None:
    # Total over its input: accounting must never turn a completed provider response into a run
    # failure, because the provider call may already be billed.
    assert avoided_usd_from_aigw(payload) == AvoidedCost()


def test_an_amount_at_the_contract_precision_bound_survives_exactly() -> None:
    amount = "1" * 18 + "." + "0" * 32 + "1"
    payload = _aigw(
        direct_cost={"status": "reported", "amount": amount, "unit": OPENROUTER_CREDIT_UNIT}
    )

    assert avoided_usd_from_aigw(payload).usd == Decimal(amount)


# ── test 16: each total sums its own provenance and reports all three counts ───────────────────


def test_each_total_sums_only_its_own_provenance_and_all_three_counts_are_kept() -> None:
    counters = RunCacheCounters()
    counters.record_saved_cost(Decimal("0.01"), "reported")
    counters.record_saved_cost(Decimal("0.02"), "reported")
    counters.record_saved_cost(Decimal("5"), "archive_matched")
    counters.record_saved_cost(None, None)

    assert counters.saved_cost_usd == Decimal("0.03")
    assert counters.saved_cost_archive_usd == Decimal("5")
    assert (counters.reported_hits, counters.archive_hits, counters.unpriced_hits) == (2, 1, 1)
    assert counters.saved_cost_observed is True


def test_a_provenance_with_no_hits_publishes_no_total() -> None:
    # "No such hit" and "such hits saved nothing" are different answers, so an absent key states
    # the first and a `0` would misstate it.
    counters = RunCacheCounters()
    counters.record_saved_cost(Decimal("1"), "archive_matched")

    attributes = counters.attributes()

    assert attributes[SAVED_COST_ARCHIVE_USD] == "1"
    assert SAVED_COST_USD not in attributes
    assert attributes[SAVED_COST_REPORTED_HITS] == 0


def test_the_totals_publish_as_exact_decimal_strings_beside_their_counts() -> None:
    counters = RunCacheCounters()
    counters.record_saved_cost(Decimal("0.10"), "reported")
    counters.record_saved_cost(Decimal("0.20"), "reported")
    counters.record_saved_cost(Decimal("7"), "archive_matched")

    attributes = counters.attributes()

    assert attributes[SAVED_COST_USD] == "0.30"
    assert attributes[SAVED_COST_ARCHIVE_USD] == "7"
    assert attributes[SAVED_COST_REPORTED_HITS] == 2
    assert attributes[SAVED_COST_ARCHIVE_HITS] == 1
    assert attributes[SAVED_COST_UNPRICED_HITS] == 0


# ── test 5: two accumulators, never summed, and no third exists ────────────────────────────────


def test_archive_money_is_never_summed_into_the_provider_authored_total() -> None:
    counters = RunCacheCounters()
    counters.record_saved_cost(Decimal("0.03"), "reported")
    counters.record_saved_cost(Decimal("5"), "archive_matched")

    attributes = counters.attributes()

    assert attributes[SAVED_COST_USD] == "0.03"
    assert attributes[SAVED_COST_ARCHIVE_USD] == "5"
    # No combined key exists, so a consumer cannot reach one even by accident.
    assert not any(
        "total" in key or "combined" in key for key in attributes if key.startswith("cache.")
    )


def test_the_counter_carries_exactly_two_saved_cost_accumulators() -> None:
    # Structural, not behavioural: a future third accumulator (say a combined total) would fail
    # here even if nothing read it yet.
    saved_cost_fields = {
        field.name for field in fields(RunCacheCounters) if "saved_cost" in field.name
    }

    assert saved_cost_fields == {"saved_cost_usd", "saved_cost_archive_usd"}


def test_a_run_that_saw_no_hit_publishes_no_saved_cost_at_all() -> None:
    # The existing no-hit shape must not grow three zeroes and a dash on every run.
    counters = RunCacheCounters()
    counters.record("miss", None)

    attributes = counters.attributes()

    assert SAVED_COST_USD not in attributes
    assert all(not key.startswith("cache.saved_cost") for key in attributes)


# --- the three SavedCostProvenance spellings must not drift (S5/S7) -----------------------------


def test_every_saved_cost_provenance_literal_declares_the_same_members() -> None:
    """INVARIANT: one vocabulary, spelled in three places, with nothing to keep them equal.

    `SavedCostProvenance` is declared independently in `url4.observe` (the dependency-free
    observation leaf), in `world.accounting`, and in `runner.cache_counters`. The duplication is
    deliberate — `test_only_engine_extensions_import_url4` forbids the counters from importing the
    engine — and each site carries a "change both together" comment. A comment cannot fail CI.

    WHY drift is expensive rather than cosmetic: a third provenance added at the producer but not
    at the counter does not raise. `SavedCostTotals` routes an unrecognised provenance to the
    unpriced bucket, so the money silently stops being totalled while the hit still counts as
    covered — a total that quietly understates itself is worse than one that breaks.
    """
    from typing import get_args

    from screamingface_engine.runner.cache_counters import SavedCostProvenance as CounterProvenance
    from screamingface_engine.world.accounting import SavedCostProvenance as AccountingProvenance
    from url4.observe import SavedCostProvenance as WireProvenance

    wire = frozenset(get_args(WireProvenance.__value__))
    accounting = frozenset(get_args(AccountingProvenance))
    counter = frozenset(get_args(CounterProvenance))

    assert wire == {"reported", "archive_matched"}
    assert accounting == wire
    assert counter == wire


# ── the retry withdrawal: a hit that followed a transport retry is never priced ─────────────────


def test_a_hit_after_a_transport_retry_is_not_priced() -> None:
    """A retried attempt may already have been billed, so its cache hit proves no saving.

    Attempt 1 can be processed and billed by the provider with its response lost in transit;
    attempt 2 then hits the row attempt 1 wrote. Reporting the reference cost as a SAVING would
    claim the cache avoided money that was in fact just spent.
    """
    payload = _aigw(
        direct_cost={
            "status": "reported",
            "amount": "9.99",
            "unit": OPENROUTER_CREDIT_UNIT,
            "source": "openrouter.usage.cost",
        }
    )
    retried = CacheOutcome(status="hit", reason=None, key="ab12", age_s=3, retried=True)

    # The price IS present in the block — this is a withdrawal, not an absence of evidence.
    assert avoided_usd_from_aigw(payload) == AvoidedCost(usd=Decimal("9.99"), provenance="reported")
    assert avoided_usd_for_outcome(payload, retried) == AvoidedCost()


def test_a_hit_with_no_retry_is_still_priced() -> None:
    """The withdrawal is narrow: an ordinary hit keeps reporting what it avoided."""
    payload = _aigw(
        direct_cost={
            "status": "reported",
            "amount": "9.99",
            "unit": OPENROUTER_CREDIT_UNIT,
            "source": "openrouter.usage.cost",
        }
    )
    plain = CacheOutcome(status="hit", reason=None, key="ab12", age_s=3)

    assert avoided_usd_for_outcome(payload, plain) == AvoidedCost(
        usd=Decimal("9.99"), provenance="reported"
    )


def test_a_withdrawn_price_lands_in_the_unpriced_bucket_and_no_total() -> None:
    """The hit is not erased — it is counted without a price, which is the honest report."""
    counters = RunCacheCounters()
    counters.record("hit", None)
    withdrawn = avoided_usd_for_outcome(
        _aigw(direct_cost={"status": "reported", "amount": "1", "unit": OPENROUTER_CREDIT_UNIT}),
        CacheOutcome(status="hit", reason=None, key=None, age_s=None, retried=True),
    )
    counters.record_saved_cost(withdrawn.usd, withdrawn.provenance)

    assert counters.hits == 1
    assert counters.unpriced_hits == 1
    assert counters.saved_cost_usd is None
    assert counters.saved_cost_archive_usd is None
