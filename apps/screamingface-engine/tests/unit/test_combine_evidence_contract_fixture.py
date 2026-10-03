"""The combine evidence the SDK decodes is the evidence the Engine writes (OME-1289 E4a, unit 12).

FEATURE: ``data/combine_contract/evidence_cases.json`` holds the canonical JSON of the evidence the
real combine core produces for 25 fixed scenarios: every reducer, every evidence kind, both abstain
reasons, a failed and an empty member, and the three signal families.
STORY: as a maintainer, I change the evidence model on one side and a test on the other side fails,
instead of the SDK decoder and its hand-copied test wire drifting from the Engine silently.
INVARIANT defended: this is a CONTRACT FIXTURE, not an oracle. The scenario inputs are written by
hand; the expected evidence is whatever the Engine produces today, and the file pins it. The SDK
twin (``packages/screamingface/tests/test_combine_evidence_contract.py``) only READS the file.
A deliberate evidence change is made by running this file as a script (``write_fixture()``) and
reviewing the diff of the JSON.
A missing fixture file FAILS here; it is never skipped.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import pytest
from combine_fields_support import merge_spec, pick_spec, project_spec, step
from combine_flow_support import judge_spec
from combine_golden_support import builtin_median_spec, builtin_vote_spec
from combine_selection_support import DEFAULT_SEPARATOR, concat_spec, rank_spec
from combine_signal_support import argmax_spec, costs, filter_spec, rank_signal_spec, sources
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.benchmarks.contract import OperationOutput, encode_candidate_invocation
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.combine.ports import (
    AbstainReason,
    AccountingReader,
    EvidenceKind,
    Reducer,
    canonical_json,
)

FIXTURE = Path(__file__).parent / "data" / "combine_contract" / "evidence_cases.json"


def _evidence(
    spec: dict[str, Any],
    texts: list[str],
    signals: dict[str, str] | None = None,
    *,
    sources: dict[str, Any] | None = None,
    accounting: AccountingReader | None = None,
) -> CombineEvidence:
    outcome = run(
        spec_text(spec),
        context_text(texts, signals, sources),
        registry=BUILTIN_OPERATORS,
        accounting=accounting,
    )
    return outcome.evidence


def _plain_vote() -> CombineEvidence:
    # Two answers with two holders each: a tie, the first holder in author order wins.
    texts = ["The answer is 9", "I get 12", "So 9", "Final: 12"]
    return _evidence(builtin_vote_spec(len(texts)), texts)


def _weighted_vote() -> CombineEvidence:
    spec = vote_spec(
        5,
        extract=step("last_number@1"),
        normalize=step("numeric@1"),
        reduce=step("weighted_mode@1"),
        select=step("max_weight_holder@1"),
        weights={
            "member_1": 3.0,
            "member_2": 3.0,
            "member_3": 1.0,
            "member_4": 1.0,
            "member_5": 1.0,
        },
    )
    return _evidence(spec, ["9", "9", "12", "12", "12"])


def _median_value() -> CombineEvidence:
    # The fourth member has no number, so it is reported as empty and not counted.
    texts = ["I think 10", "20", "maybe 40", "no number here"]
    return _evidence(builtin_median_spec(len(texts), select_op="value@1"), texts)


def _judge_label() -> CombineEvidence:
    return _evidence(judge_spec(3, "label"), ["alpha", "beta", "gamma"], {"judge": " member_2\n"})


def _judge_scores() -> CombineEvidence:
    reply = canonical_json({"member_1": 0.2, "member_2": 0.9, "member_3": 0.9})
    return _evidence(judge_spec(3, "scores"), ["alpha", "beta", "gamma"], {"judge": reply})


def _pick() -> CombineEvidence:
    texts = [
        '{"a": 1, "confidence": 0.4}',
        '{"a": 2, "confidence": 0.9}',
        '{"a": 3, "confidence": 0.7}',
    ]
    return _evidence(pick_spec(3, step("by_field@1", order="max")), texts)


def _merge_with_model_field() -> CombineEvidence:
    rules = [
        {"field": "answer", "rule": "majority", "normalize": "text"},
        {"field": "score", "rule": "max"},
        {"field": "summary", "rule": "model"},
    ]
    texts = [
        '{"answer":"Paris.","score":3}',
        '{"answer":"paris","score":5}',
        '{"answer":"Lyon","score":"high"}',
    ]
    return _evidence(
        merge_spec(3, rules), texts, {"writer_summary": "Two of three members say Paris."}
    )


def _projection() -> CombineEvidence:
    texts = ['{"answer": "A"}', '{"answer": "B"}', '{"other": 1}']
    return _evidence(project_spec(3, "answer"), texts)


def _rank_by_judge() -> CombineEvidence:
    reply = canonical_json({"member_1": 0.1, "member_2": 0.8, "member_3": 0.5, "member_4": 0.8})
    return _evidence(rank_spec(4, 2, "judge"), ["one", "two", "three", "four"], {"judge": reply})


def _concat_with_collision() -> CombineEvidence:
    texts = ["A", "x" + DEFAULT_SEPARATOR + "y", "C"]
    return _evidence(concat_spec(3, separator=DEFAULT_SEPARATOR, label=True), texts)


_MEDIAN_TEXTS = ["I think 10", "20", "maybe 40", "no number here"]


def _vote_one_failed() -> CombineEvidence:
    return _evidence(builtin_vote_spec(3), ["The answer is 42", "no idea", "So 42"])


def _vote_abstain() -> CombineEvidence:
    return _evidence(builtin_vote_spec(3), ["no idea", "", "maybe"])


def _vote_field_signal() -> CombineEvidence:
    spec = vote_spec(
        3,
        extract=step("json_field@1", path="answer"),
        normalize=step("text@1"),
        reduce=step("weighted_mode@1"),
        select=step("max_weight_holder@1"),
        weights={"signal": "field:confidence"},
    )
    texts = [
        '{"answer":"A","confidence":0.9}',
        '{"answer":"B","confidence":0.3}',
        '{"answer":"B","confidence":0.4}',
    ]
    return _evidence(spec, texts)


def _median_nearest() -> CombineEvidence:
    return _evidence(builtin_median_spec(len(_MEDIAN_TEXTS)), _MEDIAN_TEXTS)


def _regex_no_match() -> CombineEvidence:
    spec = vote_spec(
        3,
        extract=step("regex@1", pattern="Final: (\\w+)", group=1),
        normalize=step("text@1"),
        reduce=step("mode@1"),
        select=step("first_holder@1"),
    )
    return _evidence(spec, ["Final: B", "Final: b", "nothing"])


def _set_normalized() -> CombineEvidence:
    spec = vote_spec(
        3,
        extract=step("whole@1"),
        normalize=step("set@1"),
        reduce=step("mode@1"),
        select=step("first_holder@1"),
    )
    return _evidence(spec, ['["Paris","Rome"]', "rome, paris", "Berlin"])


def _weighted_by(key: str) -> dict[str, Any]:
    return vote_spec(
        3,
        extract=step("last_number@1"),
        normalize=step("numeric@1"),
        reduce=step("weighted_mode@1"),
        select=step("max_weight_holder@1"),
        weights={"signal": key},
    )


def _vote_cost_signal() -> CombineEvidence:
    return _evidence(
        _weighted_by("cost_usd"),
        ["9", "9", "12"],
        sources=sources(3),
        accounting=costs(0.004, 0.001, 0.002),
    )


def _vote_judge_weights() -> CombineEvidence:
    reply = canonical_json({"member_1": 0.2, "member_2": 0.9, "member_3": 0.5})
    return _evidence(_weighted_by("score:judge"), ["9", "9", "12"], {"judge": reply})


def _argmax_cost_min() -> CombineEvidence:
    return _evidence(
        argmax_spec(3, "cost_usd", "min"),
        ["alpha", "beta", "gamma"],
        sources=sources(3),
        accounting=costs(0.004, 0.001, 0.002),
    )


def _score_texts(*values: float | None) -> list[str]:
    return [canonical_json({} if v is None else {"score": v}) for v in values]


def _rank_by_signal() -> CombineEvidence:
    return _evidence(rank_signal_spec(4, 2, "field:score", "max"), _score_texts(0.3, 0.9, 0.6, 0.1))


def _rank_cut_not_met() -> CombineEvidence:
    return _evidence(rank_signal_spec(3, 3, "field:score", "max"), _score_texts(0.3, None, 0.6))


def _confidence_texts(*values: float) -> list[str]:
    return [canonical_json({"confidence": v}) for v in values]


def _filter_threshold() -> CombineEvidence:
    spec = filter_spec(4, {"key": "field:confidence", "cmp": "ge", "value": 0.6})
    return _evidence(spec, _confidence_texts(0.9, 0.2, 0.7, 0.5))


def _filter_pattern() -> CombineEvidence:
    spec = filter_spec(3, {"pattern": "ANSWER: \\d+"})
    return _evidence(spec, ["ANSWER: 7", "no marker", "so ANSWER: 12"])


def _filter_none_pass() -> CombineEvidence:
    spec = filter_spec(4, {"key": "field:confidence", "cmp": "ge", "value": 0.95})
    return _evidence(spec, _confidence_texts(0.9, 0.2, 0.7, 0.5))


def _merge_abstain() -> CombineEvidence:
    rules = [{"field": "answer", "rule": "majority", "normalize": "text"}]
    return _evidence(merge_spec(3, rules), ['{"x":1}', '{"y":2}', '{"z":3}'])


SCENARIOS: dict[str, Callable[[], CombineEvidence]] = {
    "vote_tie": _plain_vote,
    "vote_weighted": _weighted_vote,
    "median_value": _median_value,
    "judge_label": _judge_label,
    "judge_scores": _judge_scores,
    "pick": _pick,
    "merge_model_field": _merge_with_model_field,
    "projection": _projection,
    "rank_by_judge": _rank_by_judge,
    "concat_collision": _concat_with_collision,
    "vote_one_failed": _vote_one_failed,
    "vote_abstain": _vote_abstain,
    "vote_field_signal": _vote_field_signal,
    "median_nearest": _median_nearest,
    "regex_no_match": _regex_no_match,
    "set_normalized": _set_normalized,
    "vote_cost_signal": _vote_cost_signal,
    "vote_judge_weights": _vote_judge_weights,
    "argmax_cost_min": _argmax_cost_min,
    "rank_by_signal": _rank_by_signal,
    "rank_cut_not_met": _rank_cut_not_met,
    "filter_threshold": _filter_threshold,
    "filter_pattern": _filter_pattern,
    "filter_none_pass": _filter_none_pass,
    "merge_abstain": _merge_abstain,
}


def canonical_evidence(evidence: CombineEvidence) -> str:
    """The bytes the Candidate envelope writes for one evidence (same encoder, same options)."""
    return json.dumps(evidence.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))


def write_fixture() -> None:
    """Regenerate ``evidence_cases.json`` from the real core (run this file as a script)."""
    cases = {name: json.loads(canonical_evidence(build())) for name, build in SCENARIOS.items()}
    FIXTURE.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fixture() -> dict[str, Any]:
    assert FIXTURE.is_file(), f"missing contract fixture {FIXTURE}; run write_fixture()"
    loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_engine_evidence_is_the_fixture_byte_for_byte(name: str) -> None:
    pinned = _fixture()[name]

    assert canonical_evidence(SCENARIOS[name]()) == json.dumps(
        pinned, ensure_ascii=False, separators=(",", ":")
    )


def test_the_fixture_holds_exactly_the_scenarios() -> None:
    assert sorted(_fixture()) == sorted(SCENARIOS)


def test_the_scenarios_cover_the_evidence_shapes() -> None:
    cases = {name: build() for name, build in SCENARIOS.items()}
    every = list(cases.values())

    assert {e.reducer for e in every} == set(get_args(Reducer))
    assert {e.kind for e in every} == set(get_args(EvidenceKind))
    assert {e.result.reason for e in every if e.result.status == "abstain"} == set(
        get_args(AbstainReason)
    )
    numbers = {
        key
        for e in every
        for m in e.members
        for key, value in m.signals.items()
        if isinstance(value, float)
    }
    assert {"cost_usd", "score:judge"} <= numbers
    assert any(key.startswith("field:") for key in numbers)
    assert any(e.dropped > 0 for e in every)


def test_the_scenarios_pin_the_shape_facts() -> None:
    cases = {name: build() for name, build in SCENARIOS.items()}

    assert cases["vote_tie"].tie is True
    assert cases["vote_weighted"].tally is not None
    assert [row.weight for row in cases["vote_weighted"].members] == [3.0, 3.0, 1.0, 1.0, 1.0]
    last = cases["median_value"].members[3]
    assert (last.status, last.reason) == ("fail", "empty")
    assert cases["median_value"].median is not None
    assert cases["judge_label"].judge is not None and cases["judge_label"].judge.returns == "label"
    assert (
        cases["judge_scores"].judge is not None and cases["judge_scores"].judge.returns == "scores"
    )
    # GE30: a judge-weighted vote reads the judge as a signal, so evidence.judge stays None.
    weighted = cases["vote_judge_weights"]
    assert weighted.judge is None
    assert [row.signals["score:judge"] for row in weighted.members] == [0.2, 0.9, 0.5]
    assert cases["pick"].fields is not None and cases["pick"].built is False
    merge = cases["merge_model_field"]
    assert merge.built is True
    assert merge.fields is not None and "model" in [row.rule for row in merge.fields]
    assert cases["projection"].reducer == "project"
    assert cases["rank_by_judge"].reducer == "rank"
    assert cases["concat_collision"].separator_collision is True


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_envelope_writes_each_evidence_as_the_fixture_encodes_it(name: str) -> None:
    evidence = SCENARIOS[name]()
    operation = OperationOutput(
        operation_id="op_synthesis_1",
        output="combined",
        finish_reason="stop",
        accounting=None,
        combine=evidence,
    )

    envelope = encode_candidate_invocation("combined", "stop", None, operations=[operation])

    assert f'"combine":{canonical_evidence(evidence)}' in envelope


if __name__ == "__main__":
    write_fixture()
