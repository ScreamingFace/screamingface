"""Rank and cut of a top_k@1 step in the combine evidence (E4b part 2 unit 3, PRD rank-and-cut).

FEATURE: each scored member of a ``top_k@1`` step gets its 1-based ``rank`` in the cut order, and
the evidence gets the ``cut`` (``k`` and ``order``, the default "max" filled in), also when the step
abstains.
STORY: as a researcher who cuts a panel to its top k members before a writer, I see how far each
dropped member was from the cut.
INVARIANT defended: the rank and the cut come from the one order of ``top_k@1`` (P6), so ``chosen``
is always the members ranked within ``cut.k``, in rank order (CE-I2); a member with no score has no
``rank`` key; a step that is not ``top_k@1`` writes neither key (P7, P11). Every expected rank is
computed by hand (the PRD scenarios RK-1..RK-3), never copied from the code.
"""

from __future__ import annotations

import itertools
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from combine_golden_support import combine_input
from combine_selection_support import rank_spec
from combine_signal_support import costs, rank_signal_spec, sources
from combine_support import context_text, run, spec_text
from test_combine_evidence_contract_fixture import SCENARIOS

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.operators.selection import top_k
from screamingface_engine.combine.ports import (
    Answer,
    CombineInput,
    Cut,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    SignalOrder,
    canonical_json,
)

_ORDERS: tuple[SignalOrder, ...] = ("max", "min")
_GRID_VALUES: tuple[int | None, ...] = (None, 1, 2)
_TOO_LARGE = "x" * (1024 * 1024 + 1)  # one byte over MAX_OUTPUT_READ_BYTES


def _wire(outcome: CombineOutcome) -> dict[str, Any]:
    """The evidence as the envelope writes it (by alias, absent keys left out)."""
    return outcome.evidence.model_dump(by_alias=True)


def _ranks(outcome: CombineOutcome) -> list[int | None]:
    return [member.rank for member in outcome.evidence.members]


def _score_texts(*values: float | None) -> list[str]:
    """One member text per value: ``{"score": v}``, or ``{}`` (no signal) for None."""
    return [canonical_json({} if value is None else {"score": value}) for value in values]


def _run(
    spec: dict[str, Any], texts: list[str], signals: dict[str, str] | None = None
) -> CombineOutcome:
    return run(spec_text(spec), context_text(texts, signals), registry=BUILTIN_OPERATORS)


# --- RK#1 CHAR: today's top_k order -----------------------------------------------------------


def _scored_input(member_count: int) -> CombineInput:
    answers = tuple(
        Answer(f"member_{index}", None, None, "answered", None)
        for index in range(1, member_count + 1)
    )
    return combine_input(answers)


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("max", ("member_2", "member_4", "member_1")),
        ("min", ("member_1", "member_3", "member_2")),
    ],
)
def test_top_k_keeps_author_order_on_equal_scores(
    order: SignalOrder, expected: tuple[str, ...]
) -> None:
    scores = {
        "member_1": Decimal("0.5"),
        "member_2": Decimal("0.9"),
        "member_3": Decimal("0.5"),
        "member_4": Decimal("0.9"),
    }

    selection = top_k(
        Reduction(scores=MappingProxyType(scores)), _scored_input(4), {"k": 3, "order": order}
    )

    assert selection.chosen == expected
    assert selection.tie is True


# --- RK#2..RK#4: ranks and cut on an answered step ----------------------------------------------


def test_ranks_follow_the_top_k_order_for_min() -> None:
    # RK-1: costs 0.03, 0.01, 0.02, 0.01; cheapest first, equal costs in author order:
    # member_2 (0.01), member_4 (0.01), member_3 (0.02), member_1 (0.03).
    outcome = run(
        spec_text(rank_signal_spec(4, 2, "cost_usd", "min")),
        context_text(["alpha", "beta", "gamma", "delta"], None, sources(4)),
        registry=BUILTIN_OPERATORS,
        accounting=costs(0.03, 0.01, 0.02, 0.01),
    )

    assert _ranks(outcome) == [4, 1, 3, 2]
    assert outcome.evidence.chosen == ["member_2", "member_4"]
    assert outcome.evidence.tie is False
    assert _wire(outcome)["cut"] == {"k": 2, "order": "min"}


def test_ranks_and_tie_for_max_with_equal_scores_at_the_cut() -> None:
    # RK-2: 0.9, 0.5, 0.5, high first: member_1, then member_2 and member_3 in author order.
    outcome = _run(rank_signal_spec(3, 2, "field:score", "max"), _score_texts(0.9, 0.5, 0.5))

    assert _ranks(outcome) == [1, 2, 3]
    assert outcome.evidence.chosen == ["member_1", "member_2"]
    assert outcome.evidence.tie is True
    assert _wire(outcome)["cut"] == {"k": 2, "order": "max"}


def test_cut_writes_k_and_the_default_order() -> None:
    spec = rank_spec(3, 2, "field")
    assert spec["select"]["args"] == {"k": 2}  # sf.Rank(2, by_field="score") writes no order

    outcome = _run(spec, _score_texts(0.9, 0.5, 0.5))

    assert _wire(outcome)["cut"] == {"k": 2, "order": "max"}
    assert _ranks(outcome) == [1, 2, 3]


# --- RK#5: chosen is the members ranked within k (CE-I2) --------------------------------------


def _best_first(values: tuple[int | None, ...], order: SignalOrder) -> list[int]:
    """Hand oracle: the author indexes of the scored members, best first, ties in author order."""
    scored = [(index, value) for index, value in enumerate(values) if value is not None]
    sign = -1 if order == "max" else 1
    return [index for index, _ in sorted(scored, key=lambda pair: (sign * pair[1], pair[0]))]


def _assert_grid_run(values: tuple[int | None, ...], k: int, order: SignalOrder) -> None:
    """One grid run: the ranks equal the oracle, and an answered step chooses ranks 1..k."""
    label = f"{values} k={k} {order}"
    texts = [canonical_json({} if value is None else {"s": value}) for value in values]
    outcome = _run(rank_signal_spec(4, k, "field:s", order), texts)
    best_first = _best_first(values, order)
    expected: list[int | None] = [None] * 4
    for rank, index in enumerate(best_first, start=1):
        expected[index] = rank

    assert _ranks(outcome) == expected, label
    assert _wire(outcome)["cut"] == {"k": k, "order": order}, label
    answered = outcome.evidence.result.status == "answered"
    assert answered == (len(best_first) >= k), label
    if not answered:
        return
    within = {
        member.rank: member.member_id
        for member in outcome.evidence.members
        if member.rank is not None and member.rank <= k
    }
    assert outcome.evidence.chosen == [within[rank] for rank in sorted(within)], label
    assert outcome.evidence.chosen == [f"member_{index + 1}" for index in best_first[:k]], label


def test_chosen_equals_members_ranked_within_k() -> None:
    # 81 value tuples x k in 1..4 x two orders = 648 runs of the pure core.
    grid = itertools.product(itertools.product(_GRID_VALUES, repeat=4), range(1, 5), _ORDERS)
    for values, k, order in grid:
        _assert_grid_run(values, k, order)


# --- RK#6..RK#8 -----------------------------------------------------------------------------


def test_judge_scored_rank_has_ranks() -> None:
    # RK-3: judge scores 7, 9, 8 -> member_2 (9), member_3 (8), member_1 (7).
    reply = canonical_json({"member_1": 7, "member_2": 9, "member_3": 8})

    outcome = _run(rank_spec(3, 1, "judge"), ["A", "B", "C"], {"judge": reply})

    assert _ranks(outcome) == [3, 1, 2]
    assert outcome.evidence.chosen == ["member_2"]
    assert _wire(outcome)["cut"] == {"k": 1, "order": "max"}


def test_cut_not_met_still_writes_ranks_and_cut() -> None:
    # RK-E1: k=3, only two members have a score (0.3 and 0.6).
    outcome = _run(rank_signal_spec(3, 3, "field:score", "max"), _score_texts(0.3, None, 0.6))
    wire = _wire(outcome)

    assert (wire["result"]["status"], wire["result"]["reason"]) == ("abstain", "cut_not_met")
    assert wire["chosen"] == []
    assert _ranks(outcome) == [2, None, 1]
    assert "rank" not in wire["members"][1]
    assert wire["cut"] == {"k": 3, "order": "max"}


@pytest.mark.parametrize(
    ("spec", "texts", "status", "reason"),
    [
        (
            rank_spec(3, 1, "field"),
            [canonical_json({"score": 5}), "no json here", canonical_json({"score": 7})],
            "fail",
            None,
        ),
        (
            rank_signal_spec(3, 1, "field:score", "max"),
            _score_texts(0.5, None, 0.7),
            "excluded",
            "no_signal",
        ),
    ],
    ids=["failed", "excluded"],
)
def test_unscored_member_has_no_rank_key(
    spec: dict[str, Any], texts: list[str], status: str, reason: str | None
) -> None:
    wire = _wire(_run(spec, texts))

    assert [member.get("rank") for member in wire["members"]] == [2, None, 1]
    assert "rank" not in wire["members"][1]
    assert wire["members"][1]["status"] == status
    if reason is not None:
        assert wire["members"][1]["reason"] == reason


def test_a_failed_member_with_a_judge_score_keeps_its_rank() -> None:
    # The rank follows the score, not the status (P6 "scored members"): the judge scored the
    # too-large member 0.9, so it is first, as it is chosen today.
    reply = canonical_json({"member_1": 0.1, "member_2": 0.9})

    outcome = _run(rank_spec(2, 1, "judge"), ["A", _TOO_LARGE], {"judge": reply})

    assert _ranks(outcome) == [2, 1]
    assert _wire(outcome)["members"][1]["status"] == "fail"
    assert outcome.evidence.chosen == ["member_2"]


# --- RK#9: no other step writes rank or cut -------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_steps_other_than_top_k_keep_their_bytes(name: str) -> None:
    wire = SCENARIOS[name]().model_dump(by_alias=True)
    is_top_k = "top_k@1" in wire["operators"]

    assert ("cut" in wire) is is_top_k
    if not is_top_k:
        assert all("rank" not in member for member in wire["members"])


# --- RK#10..RK#12 ---------------------------------------------------------------------------


def test_k_equal_to_scored_count_chooses_all() -> None:
    # RK-D3: member_2 fails (no JSON); three members have a score (4, 8, 6); k=3.
    texts = [
        canonical_json({"score": 4}),
        "no json here",
        canonical_json({"score": 8}),
        canonical_json({"score": 6}),
    ]

    outcome = _run(rank_spec(4, 3, "field"), texts)

    assert outcome.evidence.result.status == "answered"
    assert outcome.evidence.chosen == ["member_3", "member_4", "member_1"]
    assert _ranks(outcome) == [3, None, 1, 2]
    assert max(rank for rank in _ranks(outcome) if rank is not None) == 3
    assert outcome.evidence.tie is False


@pytest.mark.parametrize(
    "spec",
    [rank_spec(4, 2, "field"), rank_signal_spec(4, 2, "field:score", "min")],
    ids=["max", "min"],
)
def test_all_equal_scores_rank_in_author_order(spec: dict[str, Any]) -> None:
    outcome = _run(spec, _score_texts(5, 5, 5, 5))

    assert _ranks(outcome) == [1, 2, 3, 4]
    assert outcome.evidence.chosen == ["member_1", "member_2"]
    assert outcome.evidence.tie is True


@pytest.mark.parametrize(
    ("spec", "texts"),
    [
        (rank_signal_spec(3, 2, "field:score", "max"), _score_texts(None, None, None)),
        (rank_spec(3, 2, "field"), ["not json", "plain text", ""]),
    ],
    ids=["reduce_abstains", "no_voter"],
)
def test_reduce_abstain_writes_cut_without_ranks(spec: dict[str, Any], texts: list[str]) -> None:
    wire = _wire(_run(spec, texts))

    assert (wire["result"]["status"], wire["result"]["reason"]) == ("abstain", "no_votes")
    assert all("rank" not in member for member in wire["members"])
    assert wire["cut"] == {"k": 2, "order": "max"}


# --- RK-N1 guard: the hooks are select-only and not published ----------------------------------


def _reduce(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    return Reduction()


def _no_ranks(reduction: Reduction, combine_input: CombineInput, args: OpArgs) -> dict[str, int]:
    return {}


def _one_cut(args: OpArgs) -> Cut:
    return Cut(k=1, order="max")


def test_only_a_select_operator_may_declare_ranks_or_a_cut() -> None:
    with pytest.raises(ValueError):
        OperatorDescriptor("early_rank", 1, "reduce", "s", _reduce, ranks=_no_ranks)
    with pytest.raises(ValueError):
        OperatorDescriptor("early_cut", 1, "reduce", "s", _reduce, cut=_one_cut)
    top = BUILTIN_OPERATORS.resolve("top_k@1", "select")

    assert top.ranks is not None
    assert top.cut is not None
    assert {"ranks", "cut"}.isdisjoint(top.catalog_entry())
