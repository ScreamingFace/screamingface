"""sf.Mean and its block form: compile, refusals, url4 recovery and evidence (E4b unit 3)."""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
from _combine_contract import engine_operators
from _combine_flow_fixtures import members3
from _nodes import FusionNode, MeanNode, ReduceNode, lowered
from _reducer_fixtures import fixture_operators
from url4 import Expression, build

import screamingface as sf
from screamingface._case_views import _reduce_mode
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._surface.chain import Step
from screamingface._surface.lowering import lower
from screamingface.combine_evidence import CombineEvidence
from screamingface.url4 import _calls

_CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def _fusion(step: Step) -> sf.Pipeline:
    return sf.Fanout(members3()) >> step


def _url4(step: Step) -> str:
    return compile_candidate(_fusion(step), operators=engine_operators()).url4


def _raw_intent(step: Step) -> str:
    root = build(_url4(step))
    assert isinstance(root, Expression)
    return _calls(root)["synthesis_1"].raw_intent


def test_sdk_mean_compiles_mean_or_weighted_mean_by_weights() -> None:
    # Oracle: Q1 (the op follows the weights); canonical sorted JSON (combine-spec.v1).
    assert _raw_intent(sf.Mean()) == (
        '{"extract":{"args":{},"op":"last_number@1"},"members":["member_1","member_2","member_3"],'
        '"normalize":{"args":{},"op":"numeric@1"},"reduce":{"args":{},"op":"mean@1"},'
        '"reducer":"mean","schema":"screamingface.combine-spec.v1",'
        '"select":{"args":{},"op":"value@1"},"weights":null}'
    )
    assert _raw_intent(sf.Mean(select="nearest", weights=(1, 1, 2))) == (
        '{"extract":{"args":{},"op":"last_number@1"},"members":["member_1","member_2","member_3"],'
        '"normalize":{"args":{},"op":"numeric@1"},"reduce":{"args":{},"op":"weighted_mean@1"},'
        '"reducer":"mean","schema":"screamingface.combine-spec.v1",'
        '"select":{"args":{},"op":"nearest@1"},'
        '"weights":{"member_1":1.0,"member_2":1.0,"member_3":2.0}}'
    )
    confidence = json.loads(_raw_intent(sf.Mean(weights=sf.signal("field:confidence"))))
    assert confidence["weights"] == {"signal": "field:confidence"}
    assert confidence["reduce"]["op"] == "weighted_mean@1"


def test_sdk_mean_refuses_a_wrong_weight_count() -> None:
    with pytest.raises(ValueError, match="mean has 2 weights for 3 members"):
        _fusion(sf.Mean(weights=(1, 2)))
    with pytest.raises(ValueError, match=r"sf.Mean has 2 weights for 3 members"):
        _fusion(sf.Mean(over=sf.Extract("last_number"), weights=(1, 2)))


def test_sdk_mean_refuses_score_judge_weights() -> None:
    with pytest.raises(
        ValueError, match=r"Mean cannot read sf.signal\('score:judge'\): it has no judge"
    ):
        sf.Mean(weights=sf.signal("score:judge"))
    with pytest.raises(ValueError, match=r"sf.Mean cannot read sf.signal\('score:judge'\)"):
        sf.Mean(over=sf.Extract("last_number"), weights=sf.signal("score:judge"))


def test_sdk_reduce_block_mean_compiles_to_the_same_bytes_as_sf_mean() -> None:
    assert _url4(sf.Mean(over=sf.Extract("last_number"))) == _url4(sf.Mean())
    assert _url4(
        sf.Mean(over=sf.Extract("last_number"), weights=(1, 1, 2), select="nearest")
    ) == _url4(sf.Mean(select="nearest", weights=(1, 1, 2)))
    assert sf.Mean(over=sf.Extract("last_number")).select == "value"
    assert sf.Mean(over=sf.Extract("last_number", normalize="numeric")) == sf.Mean(
        over=sf.Extract("last_number")
    )
    with pytest.raises(
        ValueError,
        match=re.escape(
            "sf.Mean reads numbers, so its sf.Extract takes normalize='numeric' or none"
        ),
    ):
        sf.Mean(over=sf.Extract("last_number", normalize="text"))


# WHY factories: the mean block raised at import time in RED, so a module-level value would
# fail the whole module at collection instead of each row at run time.
@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda: sf.Mean(), MeanNode),
        (lambda: sf.Mean(select="nearest", weights=(1, 1, 2)), MeanNode),
        (lambda: sf.Mean(weights=sf.signal("field:confidence")), MeanNode),
        (lambda: sf.Mean(over=sf.Extract("last_number")), MeanNode),
        (
            lambda: sf.Mean(over="field:answer", weights=sf.signal("field:confidence")),
            ReduceNode,
        ),
        (
            lambda: sf.Mean(over="field:answer", select="nearest"),
            ReduceNode,
        ),
    ],
)
def test_url4_round_trip_rebuilds_sf_mean_and_the_mean_block(make: Any, expected: type) -> None:
    step: Step = make()
    url4 = _url4(step)
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)
    recovered = namespace["candidate"]
    assert isinstance(recovered, sf.Pipeline)
    node = lowered(recovered)
    assert type(node.synthesizer) is expected
    if expected is ReduceNode:
        authored = lower(_fusion(step))
        assert isinstance(authored, FusionNode)
        assert node.synthesizer == authored.synthesizer
    assert compile_candidate(recovered, operators=engine_operators()).url4 == url4


def test_url4_round_trip_refuses_a_mean_spec_the_sdk_does_not_write() -> None:
    # mean@1 with weights: the SDK never writes this shape, so both rebuilds refuse it.
    spec = json.loads(_raw_intent(sf.Mean()))
    spec["weights"] = {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}
    with pytest.raises(
        ValueError, match="URL4 Candidate has a mean spec this SDK version cannot rebuild"
    ):
        MeanNode._rebuild(spec, ())
    with pytest.raises(
        ValueError, match="URL4 Candidate has a mean spec this SDK version cannot rebuild"
    ):
        ReduceNode._rebuild(spec, ())


def test_sdk_refuses_an_engine_without_the_mean_operators() -> None:
    with pytest.raises(
        ValueError, match=r"unknown reduce operator 'mean'; known reduce operators: median, mode"
    ):
        compile_candidate(_fusion(sf.Mean()), operators=fixture_operators())
    with pytest.raises(ValueError, match=r"unknown reduce operator 'weighted_mean'"):
        compile_candidate(_fusion(sf.Mean(weights=(1, 1, 1))), operators=fixture_operators())


def _member(index: int, value: str) -> dict[str, Any]:
    return {
        "member_id": f"member_{index}",
        "raw": value,
        "value": value,
        "status": "answered",
        "reason": None,
        "signals": {},
        "weight": None,
        "score": None,
    }


# Hand-written oracle: the shape the Engine writes for sf.Mean() over 10, 20, 60.
_MEAN_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "mean",
    "operators": ["last_number@1", "numeric@1", "mean@1", "value@1"],
    "members": [_member(1, "10"), _member(2, "20"), _member(3, "60")],
    "tally": None,
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": True,
    "agreement": None,
    "tie": False,
    "median": None,
    "mean": "30",
    "presentation_order": None,
    "separator_collision": None,
    "signal": None,
    "result": {"member_id": None, "value": "30", "status": "answered", "reason": None},
    "dropped": 0,
    "finish_reason": "stop",
}


def test_sdk_combine_evidence_accepts_reducer_mean() -> None:
    evidence = decode_combine_evidence(copy.deepcopy(_MEAN_WIRE), "mean evidence")
    assert evidence is not None
    assert evidence.reducer == "mean"
    assert evidence.mean == "30"
    assert evidence.median is None
    assert evidence.to_dict() == _MEAN_WIRE
    assert list(evidence.to_dict()) == list(_MEAN_WIRE)
    assert _reduce_mode(evidence) == "compute"

    # A wire with no `mean` key is a median wire: it decodes with mean None and writes no key.
    plain = {k: v for k, v in _MEAN_WIRE.items() if k != "mean"} | {
        "reducer": "median",
        "median": "20",
        "operators": ["last_number@1", "numeric@1", "median@1", "value@1"],
        "result": {"member_id": None, "value": "20", "status": "answered", "reason": None},
    }
    decoded = decode_combine_evidence(plain, "median evidence")
    assert decoded is not None
    assert decoded.mean is None
    assert "mean" not in decoded.to_dict()


@pytest.mark.parametrize(("name", "operator_ids"), [("sf.Mean", ("mean@1", "weighted_mean@1"))])
def test_changelog_entries_name_the_required_operator_ids(
    name: str, operator_ids: tuple[str, ...]
) -> None:
    text = _CHANGELOG.read_text(encoding="utf-8")
    unreleased = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    entries = [b for b in unreleased.split("\n* ") if f"`{name}(" in b]
    assert entries, name
    entry = entries[0]
    assert "Requires an SF Engine whose catalog has" in entry
    for op_id in operator_ids:
        assert f"`{op_id}`" in entry


def test_frozen_record_fields_include_evidence_mean() -> None:
    names = [f.name for f in dataclasses.fields(CombineEvidence)]
    assert names[names.index("median") + 1] == "mean"
