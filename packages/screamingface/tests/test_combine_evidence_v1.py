"""The Answer-row evidence wire of the E4a combine core (OME-1289 gap, AR#9 and G7).

STORY: as a researcher, I read per-member status and reason, the computed result, the dropped
count and the signal a reducer read, decoded from the Engine's real evidence bytes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.combine_evidence import CombineAnswerRow, CombineResult, CombineSignal
from screamingface.errors import ExecutionError

_LABEL = "Case Operation combine"
_CASES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "combine_evidence_cases.json").read_text(encoding="utf-8")
)


def _decode(name: str) -> Any:
    evidence = decode_combine_evidence(copy.deepcopy(_CASES[name]), _LABEL)
    assert evidence is not None
    return evidence


@pytest.mark.parametrize("name", sorted(_CASES))
def test_sdk_decodes_answer_rows_and_result_from_shared_fixture(name: str) -> None:
    wire = _CASES[name]

    # no sort_keys: the key order is part of the wire contract
    assert json.dumps(_decode(name).to_dict()) == json.dumps(wire)


def test_decoded_fixture_values_are_typed() -> None:
    one_failed = _decode("vote_one_failed")
    assert one_failed.members[1] == CombineAnswerRow(
        member_id="member_2",
        raw=None,
        value=None,
        status="fail",
        reason="empty",
        signals={},
    )
    assert one_failed.dropped == 1
    assert one_failed.result == CombineResult("member_1", "42", "answered", None)

    abstain = _decode("vote_abstain")
    assert abstain.result.status == "abstain"
    assert abstain.result.reason == "no_votes"
    assert abstain.chosen == ()

    field_signal = _decode("vote_field_signal")
    assert field_signal.signal == CombineSignal("field:confidence", None)
    assert [row.signals["field:confidence"] for row in field_signal.members] == [0.9, 0.3, 0.4]

    median_value = _decode("median_value")
    assert median_value.built is True
    assert median_value.result.member_id is None


def _mutated(name: str, mutation: Any) -> dict[str, Any]:
    wire = copy.deepcopy(_CASES[name])
    mutation(wire)
    return wire


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda w: w["members"][0].__setitem__("status", "voted"), "members\\[0\\] status"),
        (lambda w: w["members"][1].__setitem__("reason", "bogus"), "members\\[1\\] reason"),
        (lambda w: w["result"].__setitem__("status", "fail"), "result status"),
        (lambda w: w.__setitem__("dropped", 2), "is invalid"),
        (lambda w: w["result"].__setitem__("reason", "bogus"), "result reason"),
        (
            lambda w: w["signal"] or w.__setitem__("signal", {"key": "x", "order": None}),
            "signal key must be",
        ),
        (lambda w: w["members"][0].__setitem__("signals", {"cost_usd": "1"}), "signals"),
        (lambda w: w["members"][0].__setitem__("signals", []), "signals"),
        (lambda w: w["members"][0].__setitem__("member", "member_1"), "unsupported field"),
        (lambda w: w["members"][0].pop("member_id"), "missing 'member_id'"),
        (lambda w: w.pop("result"), "missing 'result'"),
        (lambda w: w["result"].__setitem__("extra", 1), "result contains unsupported field"),
        (lambda w: w.__setitem__("dropped", True), "dropped must be an integer"),
    ],
)
def test_decoder_names_the_field_of_an_unknown_status_or_reason(
    mutation: Any, message: str
) -> None:
    with pytest.raises(ExecutionError, match=message):
        decode_combine_evidence(_mutated("vote_one_failed", mutation), _LABEL)


def test_decoder_refuses_inconsistent_results() -> None:
    abstain_with_chosen = _mutated("vote_abstain", lambda w: w.__setitem__("chosen", ["member_1"]))
    built_member = _mutated(
        "median_value", lambda w: w["result"].__setitem__("member_id", "member_1")
    )
    wrong_chosen = _mutated("vote_one_failed", lambda w: w.__setitem__("chosen", ["member_3"]))
    for wire in (abstain_with_chosen, built_member, wrong_chosen):
        with pytest.raises(ExecutionError, match="is invalid"):
            decode_combine_evidence(wire, _LABEL)


@pytest.mark.parametrize("reason", ["no_votes", "cut_not_met"])
def test_decoder_refuses_a_failed_member_with_an_abstain_reason(reason: str) -> None:
    def put(wire: dict[str, Any]) -> None:
        wire["members"][1]["reason"] = reason

    with pytest.raises(ExecutionError, match="is invalid: .*failed member.*reason"):
        decode_combine_evidence(_mutated("vote_one_failed", put), _LABEL)


def test_answer_row_invariants() -> None:
    def row(**change: Any) -> CombineAnswerRow:
        values: dict[str, Any] = {
            "member_id": "member_1",
            "raw": "1",
            "value": "1",
            "status": "answered",
            "reason": None,
            "signals": {},
        }
        return CombineAnswerRow(**{**values, **change})

    assert row(signals={"cost_usd": 1}).signals == {"cost_usd": 1.0}
    for change, error in (
        ({"reason": "empty"}, ValueError),
        ({"status": "fail"}, ValueError),
        ({"status": "fail", "reason": "empty"}, ValueError),
        ({"status": "abstain"}, ValueError),
        ({"reason": 3, "status": "fail", "value": None}, ValueError),
        ({"signals": {1: 1.0}}, TypeError),
        ({"signals": {"a": float("nan")}}, ValueError),
        ({"member_id": "m1"}, ValueError),
    ):
        with pytest.raises(error):
            row(**change)
    with pytest.raises(ValueError, match="abstain"):
        CombineResult("member_1", None, "abstain", "no_votes")
    with pytest.raises(ValueError, match="reason"):
        CombineResult(None, None, "abstain", None)
    with pytest.raises(ValueError, match="reason"):
        CombineResult("member_1", "1", "answered", "no_votes")
    with pytest.raises(ValueError, match="order"):
        CombineSignal("cost_usd", "up")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="signal key"):
        CombineSignal("cost", None)
