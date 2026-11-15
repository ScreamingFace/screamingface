"""DECIDE and JOIN refuse lost execution state; they never read it as a routing result (E4c).

Review of PR #1733 (2026-11-12): a condition selector with no result and no failed-call record,
and a taken recipe branch with no iterate result, are malformed contexts. Each fails the Case
with a permanent ``benchmark_contract_error``. Neither may choose the paid ``otherwise`` branch
or publish an empty answer as ``answered``.
"""

from __future__ import annotations

import pytest
from test_e4c_branch_endpoints import (
    _decide,
    _join,
    _keywords,
    _label_model_spec,
    _model_call,
    _panel_spec,
    _spec,
)

from url4.core.errors import ResolutionError


def test_a_condition_label_model_with_no_reply_is_a_contract_error() -> None:
    # The context names no reply for sel_1 (not even the failed-call text "$selector_1").
    with pytest.raises(ResolutionError) as caught:
        _decide(_label_model_spec(), keywords=_keywords(), selectors={})
    assert caught.value.code == "benchmark_contract_error"
    assert caught.value.permanent is True
    assert "sel_1" in str(caught.value)


def test_a_condition_label_model_with_no_selectors_key_is_a_contract_error() -> None:
    with pytest.raises(ResolutionError) as caught:
        _decide(_label_model_spec(), keywords=_keywords())
    assert caught.value.code == "benchmark_contract_error"


def test_a_failed_condition_label_model_still_takes_otherwise() -> None:
    # SL-12 stays: an explicit failed-call record is a valid false decision.
    record, _ = _decide(
        _label_model_spec(), keywords=_keywords(), selectors={"sel_1": "$selector_1"}
    )
    assert (record["selectors"][0]["status"], record["branch"]) == ("failed", "otherwise")


@pytest.mark.parametrize("taken", ["then", "otherwise"])
def test_a_taken_recipe_branch_with_no_result_is_a_contract_error(taken: str) -> None:
    spec = _spec()
    record, _ = _decide(spec, keywords=_keywords(sel_1=["math"] if taken == "then" else []))
    assert record["branch"] == taken
    other = "otherwise" if taken == "then" else "then"
    terminal = spec["terminal"][taken]
    _text, published, error = _join(
        spec, record, **{other: []}, prior=(_model_call(terminal, "an answer"),)
    )
    assert isinstance(error, ResolutionError)
    assert (error.code, error.permanent) == ("benchmark_contract_error", True)
    assert published is None


def test_a_taken_recipe_branch_with_its_result_still_answers() -> None:
    spec = _spec()
    record, _ = _decide(spec, keywords=_keywords(sel_1=["math"]))
    text, published, error = _join(
        spec, record, then=["A"], otherwise=[], prior=(_model_call("model_1", "A"),)
    )
    assert (text, error) == ("A", None)
    assert published is not None and published["result"]["status"] == "answered"


def test_a_step_branch_that_is_not_the_decision_reducer_needs_its_result() -> None:
    # A then step whose terminal is a second combine call (synthesis_2) has its own iterate.
    spec = _panel_spec("recipe", then="step")
    spec["terminal"] = {"then": "synthesis_2", "otherwise": "model_5"}
    spec["calls"]["then"] = {"min": 1, "max": 1}
    record = {
        **_decide(_spec(), keywords=_keywords(sel_1=["math"]))[0],
        "kind": "panel",
        "when": {"observe": "agreement", "cmp": ">=", "value": 0.7},
        "observed": 1.0,
        "selectors": [],
        "not_run": [
            {"branch": "otherwise", "reason": "not_selected", "model_calls": {"min": 1, "max": 1}}
        ],
        "panel": {"operation_id": "op_synthesis_1", "branch": "majority"},
    }
    _text, _published, error = _join(spec, record, otherwise=[])
    assert isinstance(error, ResolutionError)
    assert error.code == "benchmark_contract_error"
