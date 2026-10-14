"""Rank keeps the top k originals and concat joins every original (OME-1289 E4a, unit 10).

FEATURE: the next stage receives original member texts only: the k best in rank order (rank), or
all of them in author order (concat). No model rewrites them.
STORY: as a researcher, "focus on the best three" is enforced by the engine, not requested in a
prompt, and a multi-document hand-off never goes through a summarizing model.
INVARIANT defended: a cut that cannot be met abstains with ``cut_not_met``; a tie at the cut
goes to author order; no byte of a member text changes; concat makes no network call.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_selection_support import concat_spec, rank_spec
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import CombineError, canonical_json

_FOUR = ["A", "B", "C", "D"]


def _selected(*pairs: tuple[str, str]) -> str:
    return canonical_json({"selected": [{"id": m, "text": t} for m, t in pairs]})


def _rank_by_judge(texts: list[str], scores: list[float], k: int) -> Any:
    reply = canonical_json({f"member_{i}": s for i, s in enumerate(scores, start=1)})
    return run(
        spec_text(rank_spec(len(texts), k)),
        context_text(texts, {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )


def _rank_by_field(scores: list[Any], k: int) -> Any:
    texts = [canonical_json({"score": score}) for score in scores]
    return run(
        spec_text(rank_spec(len(texts), k, "field")),
        context_text(texts),
        registry=BUILTIN_OPERATORS,
    )


def _failure(
    texts: list[str], spec: dict[str, Any], signals: dict[str, str] | None = None
) -> CombineError:
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(texts, signals), registry=BUILTIN_OPERATORS)
    return caught.value


def _error(texts: list[str], spec: dict[str, Any], signals: dict[str, str] | None = None) -> str:
    return _failure(texts, spec, signals).code


def _args_error(spec: dict[str, Any], op_id: str) -> None:
    """The args check fails first, before the context (here a valid judge reply) is read."""
    reply = canonical_json({"member_1": 3, "member_2": 2, "member_3": 1})
    failure = _failure(["A", "B", "C"], spec, {"judge": reply})
    assert failure.code == "combine_spec_invalid"
    assert f"{op_id} args are invalid" in str(failure)


# --- RK-3 / OP-14 -----------------------------------------------------------------------------


def test_top_k_by_judge_scores_passes_k_originals_in_rank_order() -> None:
    outcome = _rank_by_judge(_FOUR, [0.1, 0.8, 0.3, 0.9], 2)

    assert (
        outcome.output == '{"selected":[{"id":"member_4","text":"D"},{"id":"member_2","text":"B"}]}'
    )
    evidence = outcome.evidence
    assert evidence.kind == "selection"
    assert evidence.chosen == ["member_4", "member_2"]
    assert evidence.built is True
    assert evidence.operators == ["scores@1", "top_k@1"]
    assert [m.score for m in evidence.members] == [0.1, 0.8, 0.3, 0.9]
    assert evidence.judge is not None
    assert evidence.judge.returns == "scores"
    assert evidence.judge.parsed == {
        "member_1": 0.1,
        "member_2": 0.8,
        "member_3": 0.3,
        "member_4": 0.9,
    }
    assert evidence.presentation_order == "author"


def test_top_k_copies_member_text_byte_for_byte_with_canonical_escaping() -> None:
    texts = ['say "hi"\n', "café 中文 ", " \r\n"]
    outcome = _rank_by_judge(texts, [0.5, 0.9, 0.1], 2)

    assert outcome.output == _selected(("member_2", texts[1]), ("member_1", texts[0]))


# --- RK-5 -------------------------------------------------------------------------------------


def test_top_k_by_field() -> None:
    outcome = _rank_by_field([5, 9, 7], 2)

    assert outcome.evidence.chosen == ["member_2", "member_3"]
    assert outcome.output == _selected(("member_2", '{"score":9}'), ("member_3", '{"score":7}'))
    assert outcome.evidence.judge is None
    assert outcome.evidence.presentation_order is None


# --- RK-8 -------------------------------------------------------------------------------------


def test_k_equal_to_the_member_count_has_no_cut_tie() -> None:
    outcome = _rank_by_judge(["A", "B"], [0.5, 0.5], 2)

    assert outcome.evidence.chosen == ["member_1", "member_2"]
    assert outcome.evidence.tie is False


def test_a_too_large_member_with_the_top_score_is_kept_whole() -> None:
    big = "x" * (1024 * 1024 + 1)

    outcome = _rank_by_judge(["A", big], [0.1, 0.9], 1)

    assert outcome.output == _selected(("member_2", big))
    assert outcome.evidence.chosen == ["member_2"]
    assert [(m.status, m.reason) for m in outcome.evidence.members] == [
        ("answered", None),
        ("fail", "too_large"),
    ]
    assert [m.score for m in outcome.evidence.members] == [0.1, 0.9]


# --- top_k order ------------------------------------------------------------------------------


def _rank_ordered(scores: list[float], k: int, order: Any) -> Any:
    reply = canonical_json({f"member_{i}": s for i, s in enumerate(scores, start=1)})
    spec = rank_spec(len(scores), k)
    spec["select"] = {"op": "top_k@1", "args": {"k": k, "order": order}}
    texts = [chr(64 + i) for i in range(1, len(scores) + 1)]
    return run(spec_text(spec), context_text(texts, {"judge": reply}), registry=BUILTIN_OPERATORS)


def test_top_k_order_min_keeps_the_lowest_in_order() -> None:
    outcome = _rank_ordered([0.1, 0.8, 0.3, 0.9], 2, "min")

    assert outcome.evidence.chosen == ["member_1", "member_3"]
    assert outcome.output == _selected(("member_1", "A"), ("member_3", "C"))
    assert outcome.evidence.tie is False

    tied = _rank_ordered([0.5, 0.1, 0.5, 0.5], 2, "min")
    assert tied.evidence.chosen == ["member_2", "member_1"]
    assert tied.evidence.tie is True

    highest = _rank_ordered([0.1, 0.8, 0.3, 0.9], 2, "max")
    assert highest.evidence.chosen == ["member_4", "member_2"]


# --- top_k args -------------------------------------------------------------------------------


def test_top_k_rejects_an_extra_arg_and_accepts_the_bounds() -> None:
    spec = rank_spec(3, 2)
    spec["select"] = {"op": "top_k@1", "args": {"k": 2, "x": 1}}
    _args_error(spec, "top_k@1")

    for k in (1, 3):
        outcome = _rank_by_judge(["A", "B", "C"], [3, 2, 1], k)
        assert len(outcome.evidence.chosen) == k


# --- CC-1 -------------------------------------------------------------------------------------


def test_concat_joins_in_author_order_with_labels_and_separator() -> None:
    labelled = run(
        spec_text(concat_spec(3)), context_text(["A", "B", "C"]), registry=BUILTIN_OPERATORS
    )
    assert labelled.output == "[member_1]\nA\n\n---\n\n[member_2]\nB\n\n---\n\n[member_3]\nC"
    evidence = labelled.evidence
    assert evidence.kind == "selection"
    assert evidence.chosen == ["member_1", "member_2", "member_3"]
    assert evidence.separator_collision is False
    assert evidence.built is True
    assert evidence.operators == ["join@1", "all@1"]

    plain = run(
        spec_text(concat_spec(3, label=False)),
        context_text(["A", "B", "C"]),
        registry=BUILTIN_OPERATORS,
    )
    assert plain.output == "A\n\n---\n\nB\n\n---\n\nC"


# --- CC-7 -------------------------------------------------------------------------------------


def test_joined_text_over_cap_fails() -> None:
    texts = ["x" * (1024 * 1024)] * 9

    assert _error(texts, concat_spec(9)) == "combine_input_too_large"
