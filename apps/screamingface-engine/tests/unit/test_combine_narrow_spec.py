"""The ``narrow`` key of the combine spec v1 (E4b map-reduce surface, narrow.md §2).

FEATURE: a spec may list 1 to 4 narrow steps before its main step; each one is a filter
(``filter@1`` + ``kept@1``) or a top k (``by_signal@1`` or a judge ``scores@1``, + ``top_k@1``).
STORY: as the Engine, I refuse a narrow step that is not one of those pairs, that has a stage it
must not have, or that reads two signals, before any member output is read.
INVARIANT defended: NR-S1 (1 to 4 items, exactly four keys each), NR-S2 (the ``NARROW_RULES``
pairs, a judge ``scores@1`` only), NR-S2b (the stage rules per item), NR-S3 (one signal per step:
each narrow step and the main step count apart), NR-S4 (a narrow judge read needs the judge
reply), NR-C1 (no narrow step before a step that reads the whole context: ``label@1``,
``field_rules@1``, or a gate with a judge or writer fallback). A spec without ``narrow`` parses as
before. Each refusal names a rule, never a value; every test matches the whole message.
"""

from __future__ import annotations

import re
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

from screamingface_engine.combine.ports import MAX_NARROW_STEPS, CombineError, SpecInvalid
from screamingface_engine.combine.spec import (
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


_PARSE = "combine spec is invalid: "
_NOT_FOUR = f"{_PARSE}spec: Value error, narrow must list 1 to 4 steps"
_SIGNAL_EXTRACT = "a narrow step that reads a signal or the judge has no extract"
_WHOLE_CONTEXT = "a narrow step cannot come before a label@1 or field_rules@1 reduce"
_MODEL_FALLBACK = "a narrow step cannot come before a gate with a judge or writer fallback"


def _full(message: str) -> str:
    return f"^{re.escape(message)}$"


def _refused(spec: dict[str, Any], message: str) -> None:
    with pytest.raises(SpecInvalid, match=_full(message)):
        parse_spec(spec_text(spec))


def _run_refused(spec: dict[str, Any], message: str, code: str = "combine_spec_invalid") -> None:
    with pytest.raises(CombineError, match=_full(message)) as caught:
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

    _refused(_spec([]), _NOT_FOUR)
    _refused(_spec(four + [keep_where("field:confidence", "gt", 0.1)]), _NOT_FOUR)


def test_an_explicit_null_narrow_is_refused() -> None:
    _refused(_spec(None), _NOT_FOUR)


@pytest.mark.parametrize("key", ["extract", "normalize", "reduce", "select"])
def test_a_narrow_item_needs_all_four_keys(key: str) -> None:
    item = keep_where("field:confidence", "gt", 0.5)
    del item[key]

    _refused(_spec([item]), f"{_PARSE}narrow.0.{key}: Field required")


def test_a_narrow_item_with_an_extra_key_is_refused() -> None:
    item = {**keep_where("field:confidence", "gt", 0.5), "gate": None}

    _refused(_spec([item]), f"{_PARSE}narrow.0.gate: Extra inputs are not permitted")


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

    _run_refused(
        _spec([item]),
        "a narrow step pairs filter@1 with kept@1, by_signal@1 with top_k@1, scores@1 with top_k@1",
    )


def test_a_narrow_scores_step_reads_the_judge_only() -> None:
    item = narrow_item(step("scores@1", source="values"), step("top_k@1", k=1))

    _run_refused(
        _spec([item]), f"{_PARSE}spec: Value error, a narrow scores@1 step reads the judge"
    )


def test_an_unknown_operator_in_a_narrow_item_is_unknown() -> None:
    item = narrow_item(step("filter@1", pattern="A"), step("nope@1"))

    _run_refused(
        _spec([item]),
        "combine operator 'nope@1' is not registered",
        code="combine_operator_unknown",
    )


def test_bad_args_in_a_narrow_item_are_refused() -> None:
    item = narrow_item(step("filter@1", key="field:confidence", cmp="!", value=1), step("kept@1"))

    _run_refused(
        _spec([item]), "filter@1 args are invalid: filter@1 cmp must be gt, ge, lt, le or eq"
    )


# --- NR-3 (NR-S3): one signal per step -----------------------------------------------------------


def test_a_narrow_item_has_no_weights_so_it_reads_at_most_one_signal() -> None:
    item = {**top_by("field:confidence", 1), "weights": {"signal": "field:score"}}

    _refused(_spec([item]), f"{_PARSE}narrow.0.weights: Extra inputs are not permitted")


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
    _run_refused(_spec([keep_where("conf", "gt", 0.5)]), "filter@1 reads an unknown signal")


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
    # The rule reads the resolved step (its signal read, or the judge reduce), so it runs at plan.
    _run_refused(_spec([item]), _SIGNAL_EXTRACT)


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

    _refused(_spec([item]), f"{_PARSE}spec: Value error, a narrow normalize needs a narrow extract")


def test_a_pattern_filter_without_an_extract_parses() -> None:
    assert parse_spec(spec_text(_spec([keep_matching("A")]))).narrow is not None


# --- NR-S4: a narrow judge read needs the judge reply --------------------------------------------


def test_a_narrow_judge_rank_without_the_judge_reply_is_refused() -> None:
    _run_refused(_spec([top_by_judge(1)]), "score:judge needs the judge signal")


def test_a_narrow_rank_by_score_judge_without_the_judge_reply_is_refused() -> None:
    _run_refused(_spec([top_by("score:judge", 1)]), "score:judge needs the judge signal")


# --- NR-C1: no narrow step before a step that reads the whole context ----------------------------


def test_a_narrow_step_before_a_judge_label_pick_is_refused() -> None:
    spec = vote_spec(
        3,
        [keep_where("field:confidence", "gt", 0.5)],
        reducer="judge",
        extract=None,
        normalize=None,
        reduce=step("label@1"),
        select=step("by_label@1"),
    )

    _run_refused(spec, _WHOLE_CONTEXT)


def test_a_narrow_step_before_a_field_merge_is_refused() -> None:
    spec = vote_spec(
        3,
        [keep_where("field:confidence", "gt", 0.5)],
        reducer="merge",
        extract=step("json_object@1"),
        normalize=None,
        reduce=step("field_rules@1", rules=[]),
        select=step("built@1"),
    )

    _run_refused(spec, _WHOLE_CONTEXT)


@pytest.mark.parametrize("otherwise", ["judge", "writer"])
def test_a_narrow_step_before_a_gate_with_a_model_fallback_is_refused(otherwise: str) -> None:
    gate = {"observe": "agreement", "cmp": ">=", "threshold": 0.5, "otherwise": otherwise}
    spec = vote_spec(3, [keep_where("field:confidence", "gt", 0.5)], gate=gate)

    _run_refused(spec, _MODEL_FALLBACK)


def test_a_narrow_step_before_an_abstain_gate_runs() -> None:
    gate = {"observe": "agreement", "cmp": ">=", "threshold": 0.5, "otherwise": "abstain"}
    spec = vote_spec(3, [keep_where("field:confidence", "gt", 0.5)], gate=gate)

    # Oracle: the filter keeps member_1 and member_3 (both a): agreement 1.0 >= 0.5.
    assert outcome(spec, context(_TEXTS)).evidence.chosen == ["member_1"]


def test_the_narrow_step_bound_is_four() -> None:
    assert MAX_NARROW_STEPS == 4
