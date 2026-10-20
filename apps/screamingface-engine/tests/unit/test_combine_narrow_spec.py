"""The ``narrow`` key of the combine spec v1 (E4b map-reduce surface, narrow.md §2).

FEATURE: a spec may list 1 to 4 narrow steps before its main step; each one is a filter
(``filter@1`` + ``kept@1``) or a top k (``by_signal@1`` or a judge ``scores@1``, + ``top_k@1``).
STORY: as the Engine, I refuse a narrow step that is not one of those pairs, that has a stage it
must not have, or that reads two signals, before any member output is read.
INVARIANT defended: NR-S1 (1 to 4 items, exactly four keys each), NR-S2 (the ``NARROW_RULES``
pairs, a judge ``scores@1`` only), NR-S2b (the stage rules per item), NR-S3 (one signal per step:
each narrow step and the main step count apart), NR-S4 (a narrow judge read needs the judge
reply). A spec without ``narrow`` parses as before. Each refusal names a rule, never a value.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_narrow_support import (
    context,
    json_text,
    keep_matching,
    keep_where,
    narrow_item,
    outcome,
    step,
    top_by,
    top_by_judge,
    vote_spec,
)
from combine_support import spec_text

from screamingface_engine.combine.ports import CombineError, SpecInvalid
from screamingface_engine.combine.spec import (
    MAX_NARROW_STEPS,
    NARROW_RULES,
    CombineSpec,
    NarrowSpec,
    parse_spec,
)

_TEXTS = [
    json_text(answer="A", confidence=0.9, score=1),
    json_text(answer="B", confidence=0.4, score=2),
    json_text(answer="A", confidence=0.8, score=3),
]


def _spec(narrow: Any) -> dict[str, Any]:
    spec = vote_spec(3, None)
    spec["narrow"] = narrow
    return spec


def _refused(spec: dict[str, Any], match: str) -> None:
    with pytest.raises(SpecInvalid, match=match):
        parse_spec(spec_text(spec))


def _run_refused(spec: dict[str, Any], match: str, code: str = "combine_spec_invalid") -> None:
    with pytest.raises(CombineError, match=match) as caught:
        outcome(spec, context(_TEXTS))
    assert caught.value.code == code


# --- NR-1 (NR-S1): shape -------------------------------------------------------------------------


def test_a_spec_with_narrow_parses_into_narrow_steps() -> None:
    parsed = parse_spec(spec_text(_spec([keep_where("field:confidence", "gt", 0.5)])))

    assert isinstance(parsed, CombineSpec)
    assert parsed.narrow is not None
    assert len(parsed.narrow) == 1
    (item,) = parsed.narrow
    assert isinstance(item, NarrowSpec)
    assert (item.extract, item.normalize) == (None, None)
    assert (item.reduce.op, item.select.op) == ("filter@1", "kept@1")


def test_a_spec_without_narrow_has_narrow_none() -> None:
    assert parse_spec(spec_text(vote_spec(3, None))).narrow is None


def test_narrow_takes_one_to_four_items() -> None:
    assert MAX_NARROW_STEPS == 4
    four = [keep_where("field:confidence", "gt", 0.1)] * 4
    assert len(parse_spec(spec_text(_spec(four))).narrow or ()) == 4

    _refused(_spec([]), "narrow")
    _refused(_spec(four + [keep_where("field:confidence", "gt", 0.1)]), "narrow")


def test_an_explicit_null_narrow_is_refused() -> None:
    _refused(_spec(None), "narrow")


@pytest.mark.parametrize("key", ["extract", "normalize", "reduce", "select"])
def test_a_narrow_item_needs_all_four_keys(key: str) -> None:
    item = keep_where("field:confidence", "gt", 0.5)
    del item[key]

    _refused(_spec([item]), "narrow")


def test_a_narrow_item_with_an_extra_key_is_refused() -> None:
    item = {**keep_where("field:confidence", "gt", 0.5), "gate": None}

    _refused(_spec([item]), "narrow")


# --- NR-2 (NR-S2): the narrow pairs --------------------------------------------------------------


def test_the_narrow_rules_are_the_three_pairs() -> None:
    assert dict(NARROW_RULES) == {
        "filter@1": "kept@1",
        "by_signal@1": "top_k@1",
        "scores@1": "top_k@1",
    }


@pytest.mark.parametrize(
    ("reduce", "select"),
    [
        (step("filter@1", key="field:confidence", cmp="gt", value=0.5), step("top_k@1", k=1)),
        (
            step("by_signal@1", key="field:confidence", order="max"),
            step("best_holder@1", order="max"),
        ),
        (step("scores@1", source="judge"), step("max_score@1")),
        (step("mode@1"), step("first_holder@1")),
    ],
)
def test_a_pair_that_is_not_a_narrow_rule_is_refused(
    reduce: dict[str, Any], select: dict[str, Any]
) -> None:
    extract = step("last_line@1") if reduce["op"] == "mode@1" else None
    item = narrow_item(reduce, select, extract=extract)

    _run_refused(_spec([item]), "a narrow step pairs")


def test_a_narrow_scores_step_reads_the_judge_only() -> None:
    item = narrow_item(step("scores@1", source="values"), step("top_k@1", k=1))

    _run_refused(_spec([item]), "a narrow scores@1 step reads the judge")


def test_an_unknown_operator_in_a_narrow_item_is_unknown() -> None:
    item = narrow_item(step("filter@1", pattern="A"), step("nope@1"))

    _run_refused(_spec([item]), "nope@1", code="combine_operator_unknown")


def test_bad_args_in_a_narrow_item_are_refused() -> None:
    item = narrow_item(step("filter@1", key="field:confidence", cmp="!", value=1), step("kept@1"))

    _run_refused(_spec([item]), "filter@1 args are invalid")


# --- NR-3 (NR-S3): one signal per step -----------------------------------------------------------


def test_a_narrow_item_has_no_weights_so_it_reads_at_most_one_signal() -> None:
    item = {**top_by("field:confidence", 1), "weights": {"signal": "field:score"}}

    _refused(_spec([item]), "narrow")


def test_each_step_reads_its_own_signal() -> None:
    spec = vote_spec(
        3,
        [keep_where("field:confidence", "ge", 0.5), top_by("field:score", 1)],
        reduce=step("weighted_mode@1"),
        weights={"signal": "field:confidence"},
    )

    result = outcome(spec, context(_TEXTS))

    # Oracle: the filter keeps member_1 and member_3; the top 1 by score is member_3 (3).
    assert result.evidence.chosen == ["member_3"]
    assert result.evidence.signal is not None
    assert result.evidence.signal.key == "field:confidence"


def test_the_main_step_still_reads_at_most_one_signal() -> None:
    spec = vote_spec(
        3,
        [keep_where("field:confidence", "ge", 0.5)],
        reduce=step("by_signal@1", key="field:score", order="max"),
        select=step("best_holder@1", order="max"),
        weights={"signal": "field:confidence"},
    )

    _run_refused(spec, "a combine step reads at most one signal")


def test_a_narrow_item_that_reads_an_undeclared_name_is_refused() -> None:
    _run_refused(_spec([keep_where("conf", "gt", 0.5)]), "reads an unknown signal")


# --- NR-10d (NR-S2b): stage rules per item -------------------------------------------------------


@pytest.mark.parametrize(
    "item",
    [
        narrow_item(
            step("by_signal@1", key="field:confidence", order="max"),
            step("top_k@1", k=1),
            extract=step("last_line@1"),
        ),
        narrow_item(
            step("scores@1", source="judge"), step("top_k@1", k=1), extract=step("last_line@1")
        ),
        narrow_item(
            step("filter@1", key="field:confidence", cmp="gt", value=0.5),
            step("kept@1"),
            extract=step("last_line@1"),
        ),
    ],
    ids=["by_signal", "scores", "filter_threshold"],
)
def test_a_signal_or_judge_narrow_item_has_no_extract(item: dict[str, Any]) -> None:
    _refused(_spec([item]), "narrow")


def test_a_pattern_filter_may_have_an_extract_and_a_normalize() -> None:
    item = narrow_item(
        step("filter@1", pattern="a"),
        step("kept@1"),
        extract=step("last_line@1"),
        normalize=step("text@1"),
    )

    parsed = parse_spec(spec_text(_spec([item])))

    assert parsed.narrow is not None
    assert parsed.narrow[0].extract is not None


def test_a_narrow_normalize_needs_an_extract() -> None:
    item = narrow_item(step("filter@1", pattern="a"), step("kept@1"), normalize=step("text@1"))

    _refused(_spec([item]), "narrow")


def test_a_pattern_filter_without_an_extract_parses() -> None:
    assert parse_spec(spec_text(_spec([keep_matching("A")]))).narrow is not None


# --- NR-S4: a narrow judge read needs the judge reply --------------------------------------------


def test_a_narrow_judge_rank_without_the_judge_reply_is_refused() -> None:
    _run_refused(_spec([top_by_judge(1)]), "needs the judge signal")


def test_a_narrow_rank_by_score_judge_without_the_judge_reply_is_refused() -> None:
    _run_refused(_spec([top_by("score:judge", 1)]), "needs the judge signal")
