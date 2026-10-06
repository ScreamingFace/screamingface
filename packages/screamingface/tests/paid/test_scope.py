"""Free tests of the button's `scope` choice — which Benchmarks one press runs.

INVARIANT: a press never runs a wrong shelf silently. A scope word nobody defined, or a
picked kind of Benchmark that the live Engine lists none of, is a failure before any
spend, never an empty (and therefore green) run.
"""

from __future__ import annotations

import pytest
from _scope import UnknownScopeError, pick_shelf, resolve_scope

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
