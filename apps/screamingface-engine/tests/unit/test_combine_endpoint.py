"""The pure combine core, ``run_combine`` (FW-4, FW-5, FW-6, FW-9, FW-10, FW-16, FW-17;
OME-1289 E4a, unit 1).

FEATURE: run a reducer spec over member outputs with pure functions, never a model.
Every test uses the fake operators of ``combine_support``; no built-in operator is involved, and
no url4 node is needed -- the url4 route is tested in ``test_world_combine.py``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from combine_support import (
    FAKE_REGISTRY,
    context_text,
    run,
    spec_text,
    vote_spec,
)
from pydantic import ValidationError

from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.evidence import AnswerRecord, CombineEvidence
from screamingface_engine.combine.ports import (
    CombineError,
    CombineInput,
    FieldReading,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Stage,
    TallyRow,
)
from screamingface_engine.combine.registry import OperatorRegistry

_MIB = 1024 * 1024


def _failure(intent: str, context: str, params: dict[str, str] | None = None) -> CombineError:
    """Run the core and return the CombineError it raises."""
    with pytest.raises(CombineError) as caught:
        run(intent, context, params=params)
    return caught.value


# --- FW-4 -----------------------------------------------------------------------------------


def test_endpoint_returns_first_holder_text_byte_for_byte() -> None:
    texts = [" A\r\n é x ", "b x", " y\t"]
    outcome = run(spec_text(vote_spec(3)), context_text(texts))
    assert outcome.output == texts[0]
    assert outcome.evidence.chosen == ["member_1"]


# --- U1-7 -----------------------------------------------------------------------------------


def test_vote_evidence_has_every_pinned_field() -> None:
    outcome = run(spec_text(vote_spec(3)), context_text(["x", "  ", "y X"]))
    assert outcome.evidence.model_dump(by_alias=True) == {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["fake_last_word@1", "fake_lower@1", "fake_count@1", "fake_first@1"],
        "members": [
            {"member_id": "member_1", "raw": "x", "value": "x", "status": "answered",
             "reason": None, "signals": {}, "weight": None, "score": None},
            {"member_id": "member_2", "raw": None, "value": None, "status": "fail",
             "reason": "empty", "signals": {}, "weight": None, "score": None},
            {"member_id": "member_3", "raw": "X", "value": "x", "status": "answered",
             "reason": None, "signals": {}, "weight": None, "score": None},
        ],
        "tally": [{"value": "x", "score": 2.0, "holders": ["member_1", "member_3"]}],
        "judge": None,
        "fields": None,
        "chosen": ["member_1"],
        "built": False,
        "agreement": 1.0,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": None,
        "result": {"member_id": "member_1", "value": "x", "status": "answered", "reason": None},
        "dropped": 1,
        "finish_reason": "stop",
    }  # fmt: skip


def test_evidence_keys_are_in_the_pinned_order() -> None:
    outcome = run(spec_text(vote_spec(2)), context_text(["a", "b"]))
    assert list(json.loads(outcome.evidence.model_dump_json(by_alias=True))) == [
        "schema", "kind", "reducer", "operators", "members", "tally", "judge", "fields",
        "chosen", "built", "agreement", "tie", "median", "presentation_order",
        "separator_collision", "signal", "result", "dropped", "finish_reason",
    ]  # fmt: skip


def test_evidence_carries_float_weights_and_exact_scores_from_a_weight_aware_reduce() -> None:
    weights = {"member_1": 2, "member_2": 1.5, "member_3": 1}
    spec = vote_spec(3, weights=weights, reduce={"op": "fake_weighted@1", "args": {}})
    evidence = run(spec_text(spec), context_text(["a", "b", "b"])).evidence
    assert [row.weight for row in evidence.members] == [2.0, 1.5, 1.0]
    assert evidence.tally is not None
    assert [(row.value, row.score, row.holders) for row in evidence.tally] == [
        ("b", 2.5, ["member_2", "member_3"]),
        ("a", 2.0, ["member_1"]),
    ]
    assert evidence.agreement == float(Decimal("2.5") / Decimal("4.5"))
    assert evidence.chosen == ["member_2"]


def _registry_with(name: str, stage: Stage, operator: Any) -> OperatorRegistry:
    return OperatorRegistry((*FAKE_REGISTRY, OperatorDescriptor(name, 1, stage, "t.", operator)))


def _tally_reduce(rows: tuple[TallyRow, ...]) -> Any:
    def reduce(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
        return Reduction(tally=rows)

    return reduce


def _run_tally(rows: tuple[TallyRow, ...]) -> CombineOutcome:
    registry = _registry_with("fake_rows", "reduce", _tally_reduce(rows))
    spec = vote_spec(3, reduce={"op": "fake_rows@1", "args": {}})
    return run(spec_text(spec), context_text(["a", "b", "b"]), registry=registry)


@pytest.mark.parametrize(
    "rows",
    [
        (TallyRow("a", Decimal(1), ("member_1",)), TallyRow("b", Decimal(2), ("member_2",))),
        (TallyRow("a", Decimal(1), ("member_3",)), TallyRow("b", Decimal(1), ("member_1",))),
        (TallyRow("b", Decimal(2), ("member_3", "member_2")),),
    ],
    ids=["score-ascending", "tie-by-later-first-holder", "holders-out-of-author-order"],
)
def test_an_unsorted_tally_from_a_plugin_is_a_runtime_error_and_is_not_re_sorted(
    rows: tuple[TallyRow, ...],
) -> None:
    with pytest.raises(RuntimeError, match=r"fake_rows@1 returned an unsorted tally") as caught:
        _run_tally(rows)
    assert not isinstance(caught.value, CombineError)


def test_a_tally_naming_no_holder_or_a_stranger_is_a_runtime_error() -> None:
    for holders in ((), ("member_9",)):
        with pytest.raises(RuntimeError, match=r"fake_rows@1 returned an invalid tally"):
            _run_tally((TallyRow("a", Decimal(1), holders),))


def test_the_tally_order_is_checked_on_decimals_not_on_floats() -> None:
    """Two scores that are one float but two Decimals: the Decimal order is the truth."""
    rows = (
        TallyRow("b", Decimal("1.0000000000000000001"), ("member_2",)),
        TallyRow("a", Decimal(1), ("member_1",)),
    )
    evidence = _run_tally(rows).evidence
    assert evidence.tally is not None
    assert [row.value for row in evidence.tally] == ["b", "a"]
    assert [row.score for row in evidence.tally] == [1.0, 1.0]
    assert evidence.chosen == ["member_2"]  # fake_first reads rows[0], the Decimal winner


def test_evidence_rejects_a_chosen_member_outside_the_members() -> None:
    outcome = run(spec_text(vote_spec(2)), context_text(["a", "b"]))
    data = outcome.evidence.model_dump(by_alias=True)
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "chosen": ["member_9"]})
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "chosen": ["member_1", "member_1"]})
    row = AnswerRecord.model_validate(data["members"][0]).model_dump()
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "members": [row, row]})
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "dropped": 1})  # no member failed
    abstain = {"member_id": None, "value": None, "status": "abstain", "reason": "no_votes"}
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "result": abstain})  # abstain with a chosen member
    with pytest.raises(ValidationError):
        CombineEvidence.model_validate({**data, "built": True})  # built with a member result


# --- FW-6 -----------------------------------------------------------------------------------


def test_endpoint_raises_combine_operator_unknown_for_unregistered_id() -> None:
    spec = vote_spec(2, extract={"op": "fake_last_word@9", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_operator_unknown"
    assert "fake_last_word@9" in str(error)


def test_endpoint_rejects_an_operator_at_the_wrong_stage() -> None:
    spec = vote_spec(2, select={"op": "fake_count@1", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_spec_invalid"
    assert "fake_count@1" in str(error)


# --- U1-10 ----------------------------------------------------------------------------------


def test_operator_args_are_checked_before_the_context_is_read() -> None:
    spec = vote_spec(2, extract={"op": "fake_args@1", "args": {"sep": 1}})
    error = _failure(spec_text(spec), "this context is not json")
    assert error.code == "combine_spec_invalid"
    assert "fake_args@1 args are invalid" in str(error)
    assert "context" not in str(error)


# --- FW-9 -----------------------------------------------------------------------------------


def _oversize_context() -> tuple[str, str]:
    return spec_text(vote_spec(3)), "x" * (64 * _MIB + 1)


def _too_many_members() -> tuple[str, str]:
    return spec_text(vote_spec(257)), "not json"


def _oversize_context_with_an_invalid_spec() -> tuple[str, str]:
    """The context cap is checked BEFORE the spec is parsed: a bad spec must not hide it."""
    return "not json", "x" * (64 * _MIB + 1)


def _oversize_intent() -> tuple[str, str]:
    return "x" * (64 * 1024 + 1), context_text(["a"])


@pytest.mark.parametrize(
    "make",
    [
        _oversize_context,
        _oversize_context_with_an_invalid_spec,
        _too_many_members,
        _oversize_intent,
    ],
    ids=[
        "context-64-mib-plus-1",
        "context-cap-before-spec-parse",
        "257-members",
        "intent-64-kib-plus-1",
    ],
)
def test_oversize_context_raises_before_parsing_outputs(make: Any) -> None:
    intent, context = make()
    error = _failure(intent, context)
    assert error.code == "combine_input_too_large"


# --- FW-10 ----------------------------------------------------------------------------------


def test_oversize_member_output_gets_too_large_status() -> None:
    texts = ["a x", "w " * _MIB, "c x"]
    outcome = run(spec_text(vote_spec(3)), context_text(texts))
    evidence = outcome.evidence
    skipped = evidence.members[1]
    assert (skipped.status, skipped.reason, skipped.raw, skipped.value) == (
        "fail",
        "too_large",
        None,
        None,
    )
    assert [row.status for row in evidence.members] == ["answered", "fail", "answered"]
    assert evidence.agreement == 1.0


# --- U1-14 ----------------------------------------------------------------------------------


def test_built_output_is_returned_and_marked_built() -> None:
    spec = vote_spec(2, select={"op": "fake_constant@1", "args": {}})
    outcome = run(spec_text(spec), context_text(["a", "b"]))
    evidence = outcome.evidence
    assert outcome.output == "BUILT"
    assert evidence.built is True
    assert evidence.chosen == []


def test_built_output_over_8_mib_raises_input_too_large() -> None:
    spec = vote_spec(2, select={"op": "fake_huge@1", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_input_too_large"


# --- U1-15 ----------------------------------------------------------------------------------


def test_an_invalid_selection_from_a_plugin_is_a_runtime_error() -> None:
    spec = vote_spec(2, select={"op": "fake_bad@1", "args": {}})
    with pytest.raises(RuntimeError, match=r"fake_bad@1") as caught:
        run(spec_text(spec), context_text(["a", "b"]))
    assert not isinstance(caught.value, CombineError)


# --- FW-16 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [{}, {"binding": "synthesis_1", "temperature": "0"}, {"binding": "model_1"}],
    ids=["no-params", "extra-param", "wrong-binding"],
)
def test_endpoint_rejects_params_other_than_binding(params: dict[str, str]) -> None:
    error = _failure(spec_text(vote_spec(2)), context_text(["a", "b"]), params)
    assert error.code == "combine_spec_invalid"


# --- FW-17 ----------------------------------------------------------------------------------

_LOGGER = "screamingface_engine.combine.endpoint"


def _log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _LOGGER and record.levelname == "INFO"
    ]


def test_combine_log_line_has_the_documented_fields(caplog: pytest.LogCaptureFixture) -> None:
    intent = spec_text(vote_spec(3))
    with caplog.at_level("INFO", logger=_LOGGER):
        run(intent, context_text(["x", "  ", "x"]))
        run(intent, context_text(["", "", ""]))
        _failure(intent, context_text(["a", "b", "c"]), {})
    assert _log_lines(caplog) == [
        "combine binding=synthesis_1 reducer=vote voters=2/3 agreement=1.0 tie=false outcome=ok",
        "combine binding=synthesis_1 reducer=vote voters=0/3 agreement=- tie=- "
        "outcome=abstain_no_votes",
        "combine binding=- reducer=- voters=-/- agreement=- tie=- outcome=combine_spec_invalid",
    ]


# --- U1-19 ----------------------------------------------------------------------------------


def _judge_spec() -> dict[str, Any]:
    return vote_spec(
        2,
        reducer="judge",
        extract=None,
        normalize=None,
        reduce={"op": "fake_all_parts@1", "args": {}},
        select={"op": "fake_constant@1", "args": {}},
    )


def test_presentation_order_is_author_when_a_judge_signal_is_present() -> None:
    context = context_text(["a x", "b y"], {"judge": "member_1"})
    assert run(spec_text(_judge_spec()), context).evidence.presentation_order == "author"
    assert (
        run(spec_text(_judge_spec()), context_text(["a", "b"])).evidence.presentation_order is None
    )


# --- U1-20 ----------------------------------------------------------------------------------

_SENTINEL = "SENTINEL-TEXT-42"


def _sentinel_cases() -> dict[str, tuple[str, str, dict[str, str] | None]]:
    texts = [f"{_SENTINEL} x", f"{_SENTINEL} y"]
    context = context_text(texts)
    unknown = vote_spec(2, extract={"op": "fake_last_word@9", "args": {}})
    bad_args = vote_spec(2, extract={"op": "fake_args@1", "args": {"sep": 1}})
    huge = vote_spec(2, select={"op": "fake_huge@1", "args": {}})
    return {
        "operator-unknown": (spec_text(unknown), context, None),
        "spec-invalid": (spec_text(vote_spec(2, surprise=1)), context, None),
        "bad-args": (spec_text(bad_args), context, None),
        "context-mismatch": (spec_text(vote_spec(3)), context, None),
        "bad-params": (spec_text(vote_spec(2)), context, {}),
        "output-too-large": (spec_text(huge), context, None),
        "context-too-large": (spec_text(vote_spec(2)), _SENTINEL + "x" * (64 * _MIB), None),
    }


@pytest.mark.parametrize("case", list(_sentinel_cases()))
def test_failure_messages_never_echo_member_text(case: str) -> None:
    intent, context, params = _sentinel_cases()[case]
    assert _SENTINEL not in str(_failure(intent, context, params))


# --- members are read in SPEC order, never in context key order -----------------------------


def test_members_follow_the_spec_order_not_the_context_key_order() -> None:
    spec = vote_spec(3, members=["member_3", "member_1", "member_2"])
    voted = run(spec_text(spec), context_text(["a x", "b y", "c y"]))
    assert [row.member_id for row in voted.evidence.members] == ["member_3", "member_1", "member_2"]
    assert voted.evidence.tally is not None
    assert voted.evidence.tally[0].holders == ["member_3", "member_2"]
    assert voted.output == "c y"  # y wins; its first holder in SPEC order is member_3
    tied = run(spec_text(spec), context_text(["a x", "b y", "c z"]))
    assert tied.evidence.tie is True
    assert tied.output == "c z"  # a 3-way tie goes to the first member of the SPEC


# --- every part of a Reduction reaches the evidence -----------------------------------------


def _all_parts_spec(reduce_op: str = "fake_all_parts@1") -> dict[str, Any]:
    return vote_spec(
        3,
        reducer="merge",
        extract=None,
        normalize=None,
        reduce={"op": reduce_op, "args": {}},
        select={"op": "fake_built_many@1", "args": {}},
    )


def test_a_label_judge_a_median_fields_and_a_built_multi_chosen_output_reach_the_evidence() -> None:
    outcome = run(spec_text(_all_parts_spec()), context_text(["a", "b", "c"]))
    evidence = outcome.evidence
    assert outcome.output == "TEXT"
    assert (evidence.built, evidence.chosen, evidence.tie, evidence.agreement) == (
        True,
        ["member_1", "member_3"],
        True,
        0.5,
    )
    assert evidence.median == "2.5"
    assert evidence.separator_collision is True
    assert evidence.tally is None
    assert evidence.judge is not None
    assert (evidence.judge.raw, evidence.judge.returns, evidence.judge.parsed) == (
        "member_2 wins",
        "label",
        "member_2",
    )
    assert evidence.fields is not None
    assert [(f.field, f.rule, f.values, f.result) for f in evidence.fields] == [
        ("title", "first_voter", {"member_1": "A", "member_2": None}, {"k": [1, 2.5, True, None]})
    ]
    assert [row.score for row in evidence.members] == [0.2, 0.8, None]
    json.dumps(evidence.model_dump(by_alias=True))  # JSON values only


def test_a_scores_judge_reaches_the_evidence_as_an_object() -> None:
    spec = _all_parts_spec("fake_all_parts_scores@1")
    judge = run(spec_text(spec), context_text(["a", "b", "c"])).evidence.judge
    assert judge is not None
    assert (judge.returns, judge.parsed) == ("scores", {"member_1": 0.2, "member_2": 0.8})


@pytest.mark.parametrize(
    "result",
    [Decimal("1.5"), (1, 2), {"k": Decimal(1)}, {1, 2}],
    ids=["decimal", "tuple", "nested-decimal", "set"],
)
def test_a_non_json_field_reading_is_a_runtime_error_naming_the_operator(result: object) -> None:
    def reduce(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
        return Reduction(fields=(FieldReading("f", "r", {"member_1": "x"}, result),))

    registry = _registry_with("fake_fields", "reduce", reduce)
    spec = _all_parts_spec("fake_fields@1")
    spec["select"] = {"op": "fake_constant@1", "args": {}}
    with pytest.raises(RuntimeError, match=r"fake_fields@1 returned a non-JSON field reading"):
        run(spec_text(spec), context_text(["a", "b", "c"]), registry=registry)


# --- scores must stay finite floats ------------------------------------------------------------


def test_a_score_too_large_for_a_float_is_a_spec_invalid_error() -> None:
    def reduce(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
        return Reduction(tally=(TallyRow("a", Decimal("1E+400"), ("member_1",)),))

    registry = _registry_with("fake_big", "reduce", reduce)
    spec = vote_spec(2, reduce={"op": "fake_big@1", "args": {}})
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a", "b"]), registry=registry)
    assert caught.value.code == "combine_spec_invalid"


def test_two_huge_weights_are_refused_before_any_sum_can_overflow() -> None:
    weights = {"member_1": 1e308, "member_2": 1e308}
    spec = vote_spec(2, weights=weights, reduce={"op": "fake_weighted@1", "args": {}})
    error = _failure(spec_text(spec), context_text(["a", "a"]))
    assert error.code == "combine_spec_invalid"


# --- a bug in a plugin is logged as an internal error and re-raised unchanged ------------------


def test_a_plugin_exception_is_logged_as_internal_error_and_reraised_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    spec = vote_spec(2, select={"op": "fake_boom@1", "args": {}})
    with caplog.at_level("INFO", logger=_LOGGER):
        with pytest.raises(ZeroDivisionError, match="boom"):
            run(spec_text(spec), context_text(["a x", "b y"]))
    assert _log_lines(caplog) == [
        "combine binding=synthesis_1 reducer=vote voters=2/2 agreement=- tie=- "
        "outcome=internal_error"
    ]


# --- step f: every operator is resolved before any args are checked ----------------------------


def test_an_unknown_operator_wins_over_bad_args_of_an_earlier_step() -> None:
    spec = vote_spec(
        2,
        extract={"op": "fake_args@1", "args": {"sep": 1}},
        select={"op": "fake_first@9", "args": {}},
    )
    error = _failure(spec_text(spec), context_text(["a", "b"]))
    assert error.code == "combine_operator_unknown"
    assert "fake_first@9" in str(error)
