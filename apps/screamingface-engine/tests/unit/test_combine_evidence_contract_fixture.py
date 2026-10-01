"""The combine evidence the SDK decodes is the evidence the Engine writes (OME-1289 E4a, unit 12).

FEATURE: ``data/combine_contract/evidence_cases.json`` holds the canonical JSON of the evidence the
real combine core produces for ten fixed scenarios, one for each evidence shape.
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
from typing import Any

import pytest
from combine_fields_support import merge_spec, pick_spec, project_spec, step
from combine_flow_support import judge_spec
from combine_golden_support import builtin_median_spec, builtin_vote_spec
from combine_selection_support import DEFAULT_SEPARATOR, concat_spec, rank_spec
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.benchmarks.contract import OperationOutput, encode_candidate_invocation
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.combine.ports import canonical_json

FIXTURE = Path(__file__).parent / "data" / "combine_contract" / "evidence_cases.json"


def _evidence(
    spec: dict[str, Any], texts: list[str], signals: dict[str, str] | None = None
) -> CombineEvidence:
    outcome = run(spec_text(spec), context_text(texts, signals), registry=BUILTIN_OPERATORS)
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
    # The fourth member has no number, so it is reported as skipped and not counted.
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

    assert cases["vote_tie"].tie is True
    assert cases["vote_weighted"].tally is not None
    assert [row.status for row in cases["median_value"].members][-1] != "voted"
    assert cases["median_value"].median is not None
    assert cases["judge_label"].judge is not None and cases["judge_label"].judge.returns == "label"
    assert (
        cases["judge_scores"].judge is not None and cases["judge_scores"].judge.returns == "scores"
    )
    assert cases["pick"].fields is not None and cases["pick"].built is False
    merge = cases["merge_model_field"]
    assert merge.built is True
    assert merge.fields is not None and "model" in [row.rule for row in merge.fields]
    assert cases["projection"].reducer == "project"
    assert cases["rank_by_judge"].reducer == "rank"
    assert cases["concat_collision"].separator_collision is True


def test_the_envelope_writes_each_evidence_as_the_fixture_encodes_it() -> None:
    evidence = SCENARIOS["vote_tie"]()
    operation = OperationOutput(
        operation_id="op_synthesis_1",
        output="The answer is 9",
        finish_reason="stop",
        accounting=None,
        combine=evidence,
    )

    envelope = encode_candidate_invocation("The answer is 9", "stop", None, operations=[operation])

    assert f'"combine":{canonical_evidence(evidence)}' in envelope


if __name__ == "__main__":
    write_fixture()
