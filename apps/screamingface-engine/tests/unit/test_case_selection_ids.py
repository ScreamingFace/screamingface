"""A run can name a fixed list of Case ids, not only "Cases 1 to N" (OME-1739).

FEATURE (OME-1739): a researcher's development and held-out sets are scattered Case ids, e.g.
``[3, 17, 42]`` out of LAB-Bench SeqQA's 600. A ``CaseSelection`` is that list (or the first N),
and the recipe carries it in the three places that used to carry a bare count: the Cases step,
the aggregate, and the early-result route.

INVARIANT: a list equal to 1..N is written exactly as the count, so every ``limit=N`` recipe,
and every recipe a frozen copy already pinned, stays byte-identical.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.definition import candidate
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol, early_result
from screamingface_engine.benchmarks.selection import MAX_SELECTED_CASE_IDS, CaseSelection
from url4 import Node, render

# ── the selection itself ────────────────────────────────────────────────────


def test_an_id_list_is_kept_ascending_and_written_as_a_json_array() -> None:
    selection: CaseSelection = CaseSelection.of([42, 3, 17])

    assert selection.case_ids == (3, 17, 42)
    assert selection.count == 3
    assert str(selection) == "[3,17,42]"


def test_a_list_equal_to_one_to_n_is_the_same_selection_as_the_count() -> None:
    # WHY: `cases=[1, 2, 3]` and `limit=3` run the same Cases, so they must be one recipe, one
    # cache key and one frozen copy, never two.
    assert CaseSelection.of([3, 1, 2]) == CaseSelection.first(3)
    assert str(CaseSelection.of([1, 2, 3])) == "3"
    assert CaseSelection.first(3).case_ids == (1, 2, 3)


@pytest.mark.parametrize(
    "text,expected",
    [("3", (1, 2, 3)), ("[3,17,42]", (3, 17, 42)), ("[2]", (2,)), ("[1,2]", (1, 2))],
)
def test_the_intent_text_reads_back_into_the_same_case_ids(
    text: str, expected: tuple[int, ...]
) -> None:
    assert CaseSelection.parse(text, available=50).case_ids == expected


@pytest.mark.parametrize(
    "ids",
    [
        [],  # an empty run scores nothing
        [0, 17],  # Case ids start at 1
        [-1],
        [17, 17],  # a duplicate would grade one Case twice
        [True],  # a JSON true is a Python int; it is not a Case id
        [3.0],
        ["3"],
    ],
)
def test_a_malformed_id_list_is_refused(ids: list[object]) -> None:
    with pytest.raises(ValueError):
        CaseSelection.of(ids)


def test_more_ids_than_the_cap_are_refused() -> None:
    # WHY the cap (OME-1739 limits check): the recipe rides the run URL, and the hosted edge
    # answers normally only up to about 32 KiB, which two copies of ~2,000 ids already fill.
    CaseSelection.of(range(1, MAX_SELECTED_CASE_IDS + 1)).require_within(MAX_SELECTED_CASE_IDS + 1)
    with pytest.raises(ValueError, match="at most 1000"):
        CaseSelection.of(range(2, MAX_SELECTED_CASE_IDS + 3))


@pytest.mark.parametrize(
    "text",
    ["", "0", "-1", "two", "[]", "[0]", "[3,3]", "[true]", "[3.5]", '["3"]', "3)!/x", "{}", "51"],
)
def test_malformed_intent_text_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        CaseSelection.parse(text, available=50)


def test_a_huge_count_is_refused_before_it_is_expanded() -> None:
    # INVARIANT: a hand-written recipe can say any number; it must cost nothing to refuse.
    with pytest.raises(ValueError, match="of 50 Cases"):
        CaseSelection.parse("9" * 30, available=50)


def test_an_id_above_the_benchmark_is_refused_by_name() -> None:
    selection: CaseSelection = CaseSelection.of([3, 17, 999])

    assert selection.require_within(999) is selection
    with pytest.raises(ValueError, match="999"):
        selection.require_within(600)


# ── the recipe ──────────────────────────────────────────────────────────────


def _protocol(selected: int | CaseSelection, *, early: bool = False) -> str:
    """A minimal two-step recipe: one Candidate call per Case, then the aggregate."""

    evaluation: Node = candidate("$item.input", web_search=False)
    if early:
        evaluation = early_result(
            evaluation, aggregate_route="/aggregate", selected_case_count=selected
        )
    return render(
        build_evaluation_protocol(
            cases_route="/cases",
            case_evaluation=evaluation,
            selected_case_count=selected,
            available_case_count=50,
            aggregate_route="/aggregate",
        )
    )


def test_an_id_list_rides_every_place_the_count_rode() -> None:
    url4: str = _protocol(CaseSelection.of([3, 17, 42]), early=True)

    assert "/cases()!'[3,17,42]'" in url4
    assert "!'aggregate:[3,17,42]'" in url4
    assert "!'$index:[3,17,42]'" in url4
    # url4 slices the 3 served rows, never the first 42.
    assert ";iteration.slice=0:3)" in url4


def test_a_prefix_selection_renders_the_published_count_recipe_byte_for_byte() -> None:
    assert _protocol(CaseSelection.first(3), early=True) == _protocol(3, early=True)
    assert _protocol(CaseSelection.of([1, 2, 3]), early=True) == _protocol(3, early=True)


def test_an_id_above_the_available_cases_fails_the_build() -> None:
    with pytest.raises(ValueError, match="51"):
        _protocol(CaseSelection.of([3, 51]))


def test_medxpert_builds_an_id_list_recipe_and_keeps_its_count_recipe() -> None:
    selected: str = render(MEDXPERT.protocol(CaseSelection.of([3, 17, 42])))

    assert "!'aggregate:[3,17,42]'" in selected
    assert "!'$index:[3,17,42]'" in selected
    # The Candidate is told the run's size, not the highest id (progress reads "Case 2 of 3").
    assert "case_count: '3'" in selected
    assert "case_count: '42'" not in selected


def test_resource_echoes_the_selected_ids_only_for_an_id_list() -> None:
    # INVARIANT: a `limit=` resource is unchanged; the echo is what lets the SDK refuse an
    # Engine that ignored the selection (it would run and bill all 2,450 Cases).
    limited: dict[str, object] = MEDXPERT.resource(3)
    selected: dict[str, object] = MEDXPERT.resource(cases=CaseSelection.of([3, 17, 42]))
    prefix: dict[str, object] = MEDXPERT.resource(cases=CaseSelection.of([1, 2, 3]))

    assert "selected_case_ids" not in limited
    assert selected["selected_case_count"] == 3
    assert selected["selected_case_ids"] == [3, 17, 42]
    assert prefix["selected_case_ids"] == [1, 2, 3]
    assert prefix["url4"] == limited["url4"]
    with pytest.raises(ValueError):
        MEDXPERT.resource(3, cases=CaseSelection.of([3]))
