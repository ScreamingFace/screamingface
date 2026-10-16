"""A gated vote runs end to end offline: the abstain gate and the verbalized gate (E4b part 5).


FEATURE: a Candidate that the SDK compiles with ``sf.Vote(gate=sf.Gate(...))`` runs offline in the
Engine world. The gate chooses the majority or the fallback and writes the gate record (unit 3,
GA#18a; the fallback calls are unit 4).
STORY: as a benchmark author, I keep a vote's answer only when the members agree at 70 percent or
more; when they do not, the Case abstains with ``gate_not_met``, and no extra call runs.
INVARIANT defended: an abstain gate adds no model call (the run makes exactly the member calls);
a gate abstain is a Case abstain with reason ``gate_not_met``; the evidence has no ``verifier``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"
_MEMBERS = ("prov/alpha", "prov/beta", "prov/gamma")
_TALLY = [
    {"value": "a", "score": 2.0, "holders": ["member_1", "member_2"]},
    {"value": "b", "score": 1.0, "holders": ["member_3"]},
]
_CONF = {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}
# fixture -> (member texts, Case output, abstained, gate record, result, declared)
_RUNS: dict[
    str,
    tuple[
        tuple[str, str, str],
        str,
        bool,
        dict[str, Any],
        dict[str, Any],
        dict[str, Any] | None,
    ],
] = {
    "gate_abstain_vote_candidate.url4": (
        ("A", "A", "B"),
        "",
        True,
        {
            "observe": "agreement",
            "observed": 0.6666666666666666,
            "cmp": ">=",
            "threshold": 0.7,
            "passed": False,
            "branch": "fallback",
            "otherwise": "abstain",
        },
        {"member_id": None, "value": None, "status": "abstain", "reason": "gate_not_met"},
        None,
    ),
    "gate_verbalized_vote_candidate.url4": (
        ("Confidence: 90\nA", "Confidence: 60\nA", "Confidence: 30\nB"),
        "Confidence: 90\nA",
        False,
        {
            "observe": "chosen:conf",
            "observed": 90.0,
            "cmp": ">=",
            "threshold": 80.0,
            "passed": True,
            "branch": "majority",
            "otherwise": "abstain",
        },
        {"member_id": "member_1", "value": "a", "status": "answered", "reason": None},
        _CONF,
    ),
}


def _candidate(name: str) -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = _DATA / name
    assert path.exists(), f"combine_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(_RUNS))
async def test_engine_runs_each_gated_fixture_offline(name: str) -> None:
    texts, output, abstained, gate, result, declared = _RUNS[name]
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _candidate(name),
        {model: (text, "0.001") for model, text in zip(_MEMBERS, texts, strict=True)},
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == output
    assert record.get("abstained", False) is abstained
    # exactly three calls: an abstain gate adds no call
    assert sorted(request["model"] for request in seen) == list(_MEMBERS)
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["gate"] == gate
    assert combine["result"] == result
    assert combine["tally"] == _TALLY
    assert combine["agreement"] == 0.6666666666666666
    assert combine["chosen"] == ([] if abstained else ["member_1"])
    assert "verifier" not in combine
    assert combine.get("declared") == declared
