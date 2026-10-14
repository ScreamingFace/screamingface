"""The benchmark's answer rule: decode from the benchmark resource, then the Vote/Median guards.

FEATURE: ``sf.Vote(extract="benchmark")`` groups answers the way the selected benchmark grades them
(OME-1289 gap, GP-1). The Engine writes ``answer_rule`` in the benchmark resource; the SDK reads it
from the resource it already fetches, so no extra request is made.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _combine_contract import GSM8K_RULE_WIRE, engine_operators
from _vote_run_fixtures import benchmark_resource

import screamingface as sf
from screamingface._evaluation.answer_rule import _AnswerRule
from screamingface._evaluation.benchmark import _BenchmarkResource, _decode_benchmark_resource
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
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
    "args not empty": _broken(extract={"op": "inspect_number@1", "args": {"x": 1}}),
}


@pytest.mark.parametrize("name", sorted(_MALFORMED))
def test_malformed_answer_rule_is_an_invalid_benchmark_resource(name: str) -> None:
    resource = benchmark_resource(_GSM8K)
    resource["answer_rule"] = _MALFORMED[name]

    with pytest.raises(PlanningError, match="answer_rule") as caught:
        _decode(resource)

    assert caught.value.code == "invalid_benchmark_resource"
    assert caught.value.permanent is True


@pytest.mark.parametrize("normalize", ["text", None])
def test_benchmark_extract_with_normalize_raises(normalize: str | None) -> None:
    with pytest.raises(ValueError, match="benchmark's own normalizer"):
        sf.Vote(extract="benchmark", normalize=normalize)


def test_benchmark_extract_takes_no_version_and_no_median() -> None:
    # GP#11: the rule name is "benchmark" alone; a Median needs the numeric normalizer.
    with pytest.raises(ValueError, match="takes no version"):
        sf.Vote(extract="benchmark@1")
    for extract in ("benchmark", "benchmark@1"):
        with pytest.raises(ValueError, match="numeric normalizer"):
            sf.Median(extract=extract)
    with pytest.raises(ValueError, match="benchmark's own normalizer"):
        sf.Reduce("plurality", extract=sf.Extract("benchmark", normalize="text"))


def test_benchmark_vote_value_semantics() -> None:
    vote = sf.Vote(extract="benchmark")

    assert vote.normalize is None
    assert repr(vote) == "Vote(extract='benchmark')"
    assert eval(repr(vote), {"Vote": sf.Vote}) == vote  # noqa: S307 - our own repr, no input
    # An explicit normalize='text' is the default, so it is the same Vote as sf.Vote().
    assert sf.Vote(normalize="text") == sf.Vote()


def test_vote_benchmark_extract_without_benchmark_raises() -> None:
    # BK#10: the compiler has no rule to read, so it refuses by name before any spend.
    vote = sf.Vote(extract="benchmark")
    fusion = sf.Fusion(["provider/a", "provider/b", "provider/c"], synthesizer=vote)

    with pytest.raises(ValueError, match="extract='benchmark' needs a benchmark"):
        compile_candidate(fusion, operators=engine_operators())
    with pytest.raises(ValueError, match="extract='benchmark' needs a benchmark"):
        combine_spec_text(vote, member_count=3, operators=engine_operators())
