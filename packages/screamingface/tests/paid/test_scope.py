"""Free tests of the button's `scope` choice — which Benchmarks one press runs.

INVARIANT: a press never runs a wrong shelf silently. A scope word nobody defined, or a
picked kind of Benchmark that the live Engine lists none of, is a failure before any
spend, never an empty (and therefore green) run.
"""

from __future__ import annotations

import pytest
from _scope import (
    NAMED_ENV,
    SCOPE_ENV,
    ShelfPick,
    UnknownScopeError,
    parse_named,
    pick_from_env,
    pick_shelf,
    resolve_scope,
)

# Stand-in listing: two Imported Benchmarks around one hand-built one, in the order the
# Engine would list them. It simulates `client.benchmarks.list()` as (id, origin)
# pairs; it does not prove the live Engine's origins, which the paid press does.
_LISTED: list[tuple[str, str]] = [
    ("inspect-gsm8k", "inspect_evals"),
    ("draco", "screamingface"),
    ("inspect-mmlu", "inspect_evals"),
]


def test_unset_scope_means_all() -> None:
    """The just recipe without an argument, and any caller from before the choice
    existed, must keep running the whole shelf."""
    assert resolve_scope(None) == "all"
    assert resolve_scope("") == "all"


def test_unknown_scope_fails_naming_the_allowed_values() -> None:
    """A typo would otherwise pick zero Benchmarks; the message must say what is allowed."""
    with pytest.raises(UnknownScopeError, match="all, imported, hand-built"):
        resolve_scope("handbuilt")


def test_all_keeps_every_listed_benchmark_in_engine_order() -> None:
    """`all` filters nothing, so a Benchmark of a kind added later still runs."""
    later_kind: list[tuple[str, str]] = [*_LISTED, ("future-board", "some_new_origin")]

    picked, problems = pick_shelf(later_kind, "all")

    assert picked == ["inspect-gsm8k", "draco", "inspect-mmlu", "future-board"]
    assert problems == []


def test_imported_keeps_only_inspect_evals() -> None:
    picked, problems = pick_shelf(_LISTED, "imported")

    assert picked == ["inspect-gsm8k", "inspect-mmlu"]
    assert problems == []


def test_hand_built_keeps_only_screamingface() -> None:
    picked, problems = pick_shelf(_LISTED, "hand-built")

    assert picked == ["draco"]
    assert problems == []


def test_a_picked_kind_with_nothing_listed_is_a_problem() -> None:
    """An Engine booted without the inspect extra lists only hand-built Benchmarks; an
    `all` press must not pass on those alone, and must say what is missing and why."""
    hand_built_only: list[tuple[str, str]] = [("draco", "screamingface")]

    picked, problems = pick_shelf(hand_built_only, "all")

    assert picked == ["draco"]
    assert len(problems) == 1
    assert "imported" in problems[0]
    assert "--extra benchmarks" in problems[0]


def test_hand_built_scope_does_not_require_imported_benchmarks() -> None:
    """A narrowed press checks only the kind it asked for."""
    hand_built_only: list[tuple[str, str]] = [("draco", "screamingface")]

    _, problems = pick_shelf(hand_built_only, "hand-built")

    assert problems == []


# --- The button's `benchmarks` field (OME-1522): named Benchmarks win over scope. ---


def test_blank_names_mean_unset() -> None:
    """An empty field, or one holding only commas and spaces, must leave `scope` in charge,
    so a press that never touched the field behaves exactly as before it existed."""
    assert parse_named(None) == ()
    assert parse_named("") == ()
    assert parse_named(" , ,") == ()


def test_names_are_trimmed_and_collapse_duplicates_in_first_seen_order() -> None:
    """A Benchmark named twice runs once, not twice (and is paid for once)."""
    assert parse_named(" musique, inspect-gsm8k ,musique") == ("musique", "inspect-gsm8k")


def test_names_win_over_scope() -> None:
    """Names replace the scope instead of intersecting with it: "draco under imported"
    would otherwise pick nothing and the owner would pay a boot for an empty press."""
    picked, problems = pick_shelf(_LISTED, "imported", named=("draco",))

    assert picked == ["draco"]
    assert problems == []


def test_named_picks_keep_the_engine_listing_order() -> None:
    picked, problems = pick_shelf(_LISTED, "all", named=("inspect-mmlu", "inspect-gsm8k"))

    assert picked == ["inspect-gsm8k", "inspect-mmlu"]
    assert problems == []


def test_an_unknown_name_is_a_problem_listing_the_valid_ids() -> None:
    """A typo must fail before any paid call and show what could have been typed; a
    silently dropped name would let a press come back green having skipped it."""
    _, problems = pick_shelf(_LISTED, "all", named=("draco", "musqiue"))

    assert len(problems) == 1
    assert "'musqiue'" in problems[0]
    assert "draco, inspect-gsm8k, inspect-mmlu" in problems[0]


def test_a_named_press_does_not_require_every_kind() -> None:
    """The empty-kind check guards a `scope`; naming one hand-built Benchmark on an
    Engine without the inspect extra is exactly what the owner asked for."""
    hand_built_only: list[tuple[str, str]] = [("draco", "screamingface")]

    picked, problems = pick_shelf(hand_built_only, "all", named=("draco",))

    assert picked == ["draco"]
    assert problems == []


def test_an_unknown_scope_hints_how_to_name_benchmarks() -> None:
    """`just ... test-paid-benchmarks musique` fills `scope`, not `benchmarks` (just
    arguments are positional); the error must show the one-line fix with the owner's ids,
    because the recipe has already spent the bundle downloads by the time it fails."""
    with pytest.raises(UnknownScopeError, match="test-paid-benchmarks all musique"):
        resolve_scope("musique")


# --- The hookup: env vars → the picker → the start line, as the paid test reads them. ---


def test_the_named_env_var_reaches_the_picker_and_the_start_line() -> None:
    """The paid test hands `os.environ` to `pick_from_env`; if the names were dropped on
    the way, this press would run the scope's whole kind and pay for it."""
    pick: ShelfPick = pick_from_env(_LISTED, {SCOPE_ENV: "imported", NAMED_ENV: " draco "})

    assert pick.boards == ["draco"]
    assert pick.problems == []
    assert pick.picked_by == "named draco (scope imported ignored)"


def test_without_names_the_scope_env_var_decides() -> None:
    pick: ShelfPick = pick_from_env(_LISTED, {SCOPE_ENV: "hand-built", NAMED_ENV: ""})

    assert pick.boards == ["draco"]
    assert pick.picked_by == "scope hand-built"


def test_an_empty_environment_runs_the_whole_shelf() -> None:
    """A caller that sets neither variable keeps the pre-choice behaviour: everything."""
    pick: ShelfPick = pick_from_env(_LISTED, {})

    assert pick.boards == ["inspect-gsm8k", "draco", "inspect-mmlu"]
    assert pick.picked_by == "scope all"


def test_an_unknown_name_from_the_env_var_is_a_problem() -> None:
    pick: ShelfPick = pick_from_env(_LISTED, {NAMED_ENV: "musqiue"})

    assert len(pick.problems) == 1
    assert "'musqiue'" in pick.problems[0]
