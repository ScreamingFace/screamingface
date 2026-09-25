"""The open share of the cost/score Pareto frontier (OME-1145, contract from OME-1179).

Pure computation, no database. The route test (`tests/unit/test_frontier_route.py`) proves the
inputs are the ranked table's own.

INVARIANT under every test: an entry counts only if it is ON the frontier, and it is open only
when EVERY model it declares is open (D1). Closed or unrecognised closes it (D4). An entry with no
models is excluded and counted, never guessed at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from scoreboard.classification.openness import Openness, classify_entry
from scoreboard.scores.frontier import (
    FrontierMember,
    HistoryRow,
    compute_frontier_openness,
    frontier_member_ids,
)
from scoreboard.scores.pareto import ParetoEntry

REV = "rev-1"
T0 = datetime(2026, 9, 1, tzinfo=UTC)

OPEN = ("openrouter/deepseek/deepseek-v4-pro", "openrouter/moonshotai/kimi-k2.6")
CLOSED = ("openrouter/anthropic/claude-opus-4.8",)
MIXED = ("openrouter/deepseek/deepseek-v4-pro", "openrouter/openai/gpt-5.5")
UNKNOWN = ("openrouter/deepseek/deepseek-v4-pro", "openrouter/nobody/mystery-1")


def _entry(source_id: str, score: float, cost: str | None) -> ParetoEntry:
    return ParetoEntry(
        source_id=source_id,
        spec_id=source_id,
        benchmark_revision=REV,
        score=score,
        run_cost_usd=None if cost is None else Decimal(cost),
    )


def _history(entries: list[ParetoEntry]) -> list[HistoryRow]:
    return [
        HistoryRow(
            source_id=e.source_id,
            spec_id=e.spec_id,
            score=e.score,
            run_cost_usd=e.run_cost_usd,
            submitted_at=T0 + timedelta(hours=i),
        )
        for i, e in enumerate(entries)
    ]


def _member(
    source_id: str, models: tuple[str, ...] | None, override: Openness | None = None
) -> FrontierMember:
    return FrontierMember(source_id=source_id, models=models, openness_override=override)


def _compute(entries: list[ParetoEntry], members: list[FrontierMember], *, pinned: bool = True):
    return compute_frontier_openness(
        entries,
        _history(entries),
        {m.source_id: m for m in members},
        pinned=pinned,
    )


# --- classify_entry: D1 and D4 ------------------------------------------------------------------


def test_an_entry_is_open_only_when_every_model_is_open() -> None:
    assert classify_entry(OPEN, None) == ("open", ())
    assert classify_entry(MIXED, None) == ("closed", ())
    assert classify_entry(CLOSED, None) == ("closed", ())


def test_an_unrecognised_model_closes_the_entry_and_is_named() -> None:
    assert classify_entry(UNKNOWN, None) == ("closed", ("openrouter/nobody/mystery-1",))


def test_an_entry_with_no_models_is_unidentified_not_closed() -> None:
    assert classify_entry(None, None) == ("unidentified", ())


def test_the_override_wins_over_the_models() -> None:
    """D-Q4: the operator correction path survives the migration, per entry."""
    assert classify_entry(CLOSED, "open") == ("open", ())
    assert classify_entry(OPEN, "closed") == ("closed", ())
    assert classify_entry(None, "open") == ("open", ())


# --- Only the frontier counts --------------------------------------------------------------------


def test_only_frontier_entries_count() -> None:
    """A cheaper-and-better closed entry dominates an open one, so the open one does not count."""
    entries = [_entry("closed-best", 0.9, "1.00"), _entry("open-dominated", 0.5, "2.00")]
    result = _compute(entries, [_member("closed-best", CLOSED), _member("open-dominated", OPEN)])

    assert result.frontier_size == 1
    assert (result.open_count, result.closed_count) == (0, 1)
    assert result.open_share == 0.0


def test_every_non_dominated_entry_counts() -> None:
    entries = [_entry("cheap-open", 0.5, "1.00"), _entry("dear-closed", 0.9, "5.00")]
    result = _compute(entries, [_member("cheap-open", OPEN), _member("dear-closed", CLOSED)])

    assert result.frontier_size == 2
    assert (result.open_count, result.closed_count) == (1, 1)
    assert result.open_share == 0.5


def test_an_unpriced_entry_is_off_the_frontier_and_off_the_statistic() -> None:
    """`partial` and `unavailable` rows carry a null cost (D2, D6), so they never count."""
    entries = [_entry("priced", 0.5, "1.00"), _entry("unpriced-open", 0.99, None)]
    result = _compute(entries, [_member("priced", CLOSED), _member("unpriced-open", OPEN)])

    assert result.frontier_size == 1
    assert (result.open_count, result.closed_count) == (0, 1)


# --- Exclusions are counted ----------------------------------------------------------------------


def test_an_unidentified_frontier_entry_is_excluded_and_counted() -> None:
    entries = [_entry("legacy", 0.5, "1.00"), _entry("modern", 0.9, "5.00")]
    result = _compute(entries, [_member("legacy", None), _member("modern", OPEN)])

    assert result.frontier_size == 2
    assert result.unidentified_count == 1
    assert (result.open_count, result.closed_count) == (1, 0)
    assert result.open_share == 1.0


def test_unrecognised_models_are_listed_distinct_sorted_and_capped() -> None:
    entries = [_entry(f"e{i}", 0.5 + i / 100, f"{i + 1}.00") for i in range(25)]
    members = [
        _member(f"e{i}", ("openrouter/deepseek/deepseek-v4-pro", f"openrouter/nobody/m{i:02d}"))
        for i in range(25)
    ]
    # e0 and e1 share one unknown route, so it must appear once.
    members[1] = _member("e1", ("openrouter/nobody/m00",))

    result = _compute(entries, members)

    assert result.unrecognised_models == sorted(result.unrecognised_models)
    assert len(result.unrecognised_models) == 20
    assert len(set(result.unrecognised_models)) == 20
    assert result.unrecognised_models[0] == "openrouter/nobody/m00"


# --- Nothing measured is null, not 0% (D-S) ------------------------------------------------------


def test_an_empty_frontier_has_a_null_share() -> None:
    result = _compute([], [])

    assert result.frontier_available is True
    assert result.frontier_size == 0
    assert result.open_share is None
    assert result.trend == []


def test_a_frontier_of_only_unidentified_entries_has_a_null_share() -> None:
    result = _compute([_entry("legacy", 0.5, "1.00")], [_member("legacy", None)])

    assert result.unidentified_count == 1
    assert result.open_share is None


def test_an_unpinned_board_makes_no_frontier_claim() -> None:
    """D12: no registered revision, no frontier. The same gate the table's marks use."""
    entries = [_entry("a", 0.5, "1.00")]
    result = _compute(entries, [_member("a", OPEN)], pinned=False)

    assert result.frontier_available is False
    assert result.frontier_size == 0
    assert (result.open_count, result.closed_count, result.unidentified_count) == (0, 0, 0)
    assert result.open_share is None
    assert result.trend == []


# --- The trend (D-L, D-U) -----------------------------------------------------------------------


def test_the_trend_records_each_change_in_share_chronologically() -> None:
    entries = [
        _entry("first-closed", 0.5, "1.00"),  # frontier {closed}: 0.0
        _entry("second-open", 0.9, "2.00"),  # frontier {closed, open}: 0.5
        _entry("third-dominated", 0.4, "3.00"),  # dominated: share unchanged, no point
    ]
    members = [
        _member("first-closed", CLOSED),
        _member("second-open", OPEN),
        _member("third-dominated", OPEN),
    ]

    result = _compute(entries, members)

    assert [(p.open_share, p.open_count, p.closed_count) for p in result.trend] == [
        (0.0, 0, 1),
        (0.5, 1, 1),
    ]
    assert [p.at for p in result.trend] == [T0, T0 + timedelta(hours=1)]


def test_the_trend_ends_where_the_current_share_is() -> None:
    entries = [_entry("a", 0.5, "1.00"), _entry("b", 0.9, "2.00")]
    result = _compute(entries, [_member("a", CLOSED), _member("b", OPEN)])

    assert result.trend[-1].open_share == result.open_share


def test_a_resubmission_replaces_its_specs_earlier_row_in_the_replay() -> None:
    """Best-per-spec, as the ranked query collapses it: a spec's better run supersedes its older
    one. The replay must not keep both, or a spec would count twice on the historical frontier."""
    rows = [
        HistoryRow("spec-a-old", "spec-a", 0.5, Decimal("1.00"), T0),
        HistoryRow("spec-a-new", "spec-a", 0.8, Decimal("1.00"), T0 + timedelta(hours=1)),
    ]
    current = [ParetoEntry("spec-a-new", "spec-a", REV, 0.8, Decimal("1.00"))]
    members = {
        "spec-a-old": _member("spec-a-old", CLOSED),
        "spec-a-new": _member("spec-a-new", OPEN),
    }

    result = compute_frontier_openness(current, rows, members, pinned=True)

    assert [(p.open_count, p.closed_count) for p in result.trend] == [(0, 1), (1, 0)]


# --- Only frontier members' models are read (OME-1179 constraint 4) ------------------------------


def test_models_are_needed_only_for_rows_that_were_ever_on_the_frontier() -> None:
    """The whole-board read stays minimal: a row never on any historical frontier is not read."""
    entries = [
        _entry("best", 0.9, "1.00"),
        _entry("dominated", 0.5, "2.00"),
    ]
    rows = [
        HistoryRow("dominated", "dominated", 0.5, Decimal("2.00"), T0),
        HistoryRow("best", "best", 0.9, Decimal("1.00"), T0 + timedelta(hours=1)),
    ]

    # `dominated` WAS the whole frontier before `best` arrived, so its models are needed for the
    # trend; a row that never led anywhere would not be.
    assert frontier_member_ids(entries, rows, pinned=True) == {"best", "dominated"}
    assert frontier_member_ids(entries, rows[1:], pinned=True) == {"best"}
    assert frontier_member_ids(entries, rows, pinned=False) == frozenset()


def test_an_empty_models_list_is_unidentified_not_open() -> None:
    """`all()` over nothing is True; an empty list must not read as an all-open entry."""
    assert classify_entry((), None) == ("unidentified", ())
