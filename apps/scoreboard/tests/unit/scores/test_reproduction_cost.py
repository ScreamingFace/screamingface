"""The reproduction cost: spend plus cache saving, for a row whose spend is exact (OME-1382).

FEATURE: `OME-1251` D5. A cached run spends about $0; what reproducing it costs is that spend plus
what the cache avoided. The board sums the two at the point of use and never stores the sum.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from scoreboard.scores.reproduction_cost import reproduction_cost


def test_a_complete_row_with_a_saving_costs_its_spend_plus_its_saving() -> None:
    assert reproduction_cost(Decimal("0.010000"), "complete", Decimal("1.990000")) == Decimal(
        "2.000000"
    )


def test_a_complete_row_with_no_saving_costs_exactly_its_spend() -> None:
    """INVARIANT: a row with no saving ranks exactly as it did before this change."""
    assert reproduction_cost(Decimal("1.250000"), "complete", None) == Decimal("1.250000")


def test_a_saving_of_zero_adds_nothing() -> None:
    """Zero is evidence that a hit was worth nothing, not an absent saving; the sum is unchanged."""
    assert reproduction_cost(Decimal("1.250000"), "complete", Decimal("0")) == Decimal("1.250000")


@pytest.mark.parametrize("status", ["partial", "unavailable"])
def test_a_row_without_an_exact_spend_has_no_cost_even_with_a_saving(status: str) -> None:
    """INVARIANT: a saving is never promoted to a cost.

    `partial` and `unavailable` carry no amount by contract, so they stay off every cost surface
    and the frontier. A saving beside `partial` is a lower bound on what reproducing cost, and
    publishing it as the cost would repeat OME-1143 at a smaller scale.
    """
    assert reproduction_cost(None, status, Decimal("0.500000")) is None  # type: ignore[arg-type]


def test_a_legacy_row_with_no_status_keeps_its_stored_spend() -> None:
    """A row that predates OME-822 carries no status; nothing about it changes."""
    assert reproduction_cost(Decimal("3.000000"), None, None) == Decimal("3.000000")


def test_a_legacy_row_with_a_saving_but_no_status_is_not_summed() -> None:
    """Only `complete` asserts the spend is exact, so only `complete` may be summed."""
    assert reproduction_cost(Decimal("3.000000"), None, Decimal("1.000000")) == Decimal("3.000000")


def test_no_spend_means_no_cost() -> None:
    assert reproduction_cost(None, None, None) is None


# --- D7 (owner, 2026-10-02): archive-matched money is published too ------------------------------


def test_a_complete_row_sums_spend_reported_and_archive_saving() -> None:
    assert reproduction_cost(
        Decimal("0.010000"), "complete", Decimal("1.000000"), Decimal("3.990000")
    ) == Decimal("5.000000")


def test_a_complete_row_with_only_an_archive_saving_sums_it() -> None:
    """The draco-3pass seed archive is all archive-matched: this is the case D7 exists for."""
    assert reproduction_cost(Decimal("0"), "complete", None, Decimal("4.250000")) == Decimal(
        "4.250000"
    )


def test_an_archive_saving_beside_partial_is_never_a_cost() -> None:
    assert reproduction_cost(None, "partial", None, Decimal("4.250000")) is None
