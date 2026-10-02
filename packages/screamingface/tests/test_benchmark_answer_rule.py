"""The benchmark's answer rule: decode from the benchmark resource, then the Vote/Median guards.

FEATURE: ``sf.Vote(extract="benchmark")`` groups answers the way the selected benchmark grades them
(OME-1289 gap, GP-1). The Engine writes ``answer_rule`` in the benchmark resource; the SDK reads it
from the resource it already fetches, so no extra request is made.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _combine_contract import GSM8K_RULE_WIRE
from _vote_run_fixtures import benchmark_resource

from screamingface._evaluation.answer_rule import _AnswerRule
from screamingface._evaluation.benchmark import _BenchmarkResource, _decode_benchmark_resource
from screamingface.errors import PlanningError

_GSM8K = "inspect-gsm8k"


def _decode(resource: dict[str, Any]) -> _BenchmarkResource:
    return _decode_benchmark_resource(resource, requested_id=_GSM8K, requested_limit=None)


def test_benchmark_resource_decodes_the_answer_rule() -> None:
    decoded = _decode(benchmark_resource(_GSM8K, answer_rule=GSM8K_RULE_WIRE))

    assert decoded.answer_rule == _AnswerRule(
        "inspect_number@1",
        "inspect_numeric@1",
        "inspect_ai.scorer:match(numeric=True)@0.3.263",
    )
    no_normalizer = {**GSM8K_RULE_WIRE, "normalize": None}
    assert _decode(benchmark_resource(_GSM8K, answer_rule=no_normalizer)).answer_rule == (
        _AnswerRule("inspect_number@1", None, "inspect_ai.scorer:match(numeric=True)@0.3.263")
    )
    assert _decode(benchmark_resource(_GSM8K)).answer_rule is None
    declared_none = benchmark_resource(_GSM8K)
    declared_none["answer_rule"] = None
    assert _decode(declared_none).answer_rule is None


def _broken(**change: Any) -> dict[str, Any]:
    rule = copy.deepcopy(GSM8K_RULE_WIRE)
    rule.update(change)
    return rule


def _without_grader() -> dict[str, Any]:
    rule = copy.deepcopy(GSM8K_RULE_WIRE)
    del rule["grader"]
    return rule


_MALFORMED: dict[str, Any] = {
    "not an object": "inspect_number@1",
    "extra key": _broken(extra=1),
    "no grader": _without_grader(),
    "blank grader": _broken(grader="  "),
    "extract not an object": _broken(extract="inspect_number@1"),
    "extract extra key": _broken(extract={"op": "inspect_number@1", "args": {}, "x": 1}),
    "op not pinned": _broken(extract={"op": "inspect_number", "args": {}}),
    "op version zero": _broken(extract={"op": "x@0", "args": {}}),
    "args not empty": _broken(extract={"op": "inspect_number@1", "args": {"x": 1}}),
    "normalize op not pinned": _broken(normalize={"op": "inspect_numeric", "args": {}}),
}


@pytest.mark.parametrize("name", sorted(_MALFORMED))
def test_malformed_answer_rule_is_an_invalid_benchmark_resource(name: str) -> None:
    resource = benchmark_resource(_GSM8K)
    resource["answer_rule"] = _MALFORMED[name]

    with pytest.raises(PlanningError, match="answer_rule") as caught:
        _decode(resource)

    assert caught.value.code == "invalid_benchmark_resource"
    assert caught.value.permanent is True
