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


# ---- E4b part 5 unit 4 (gate-api-fallback): GA#18b ----

_FALLBACK_DATA = Path(__file__).parent / "data" / "combine_contract"
# fallback -> (fixture, fallback route, fallback reply)
_FALLBACK_RUNS: dict[str, tuple[str, str, str]] = {
    "judge": ("gate_judge_vote_candidate.url4", "prov/judge", "member_3"),
    "writer": ("gate_writer_vote_candidate.url4", "prov/writer", "C written"),
}


def _fallback_candidate(name: str) -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = _FALLBACK_DATA / name
    assert path.exists(), f"combine_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", ["judge", "writer"])
async def test_engine_runs_each_fallback_fixture_offline(fallback: str) -> None:
    fixture, route, reply = _FALLBACK_RUNS[fallback]
    seen: list[dict[str, Any]] = []

    record = await run_candidate(
        _fallback_candidate(fixture),
        {
            "prov/alpha": ("A", "0.001"),
            "prov/beta": ("A", "0.001"),
            "prov/gamma": ("B", "0.001"),
            route: (reply, "0.001"),
        },
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    # ans:Q1: the fallback call runs on every Case (cost spent), exactly once
    assert len(seen) == 4
    assert sorted(request["model"] for request in seen) == sorted(
        ["prov/alpha", "prov/beta", "prov/gamma", route]
    )
    assert operation(record, f"op_{fallback}_1")["output"] == reply
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["agreement"] == 0.6666666666666666
    assert combine["gate"] == {
        "observe": "agreement",
        "observed": 0.6666666666666666,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": False,
        "branch": "fallback",
        "otherwise": fallback,
    }
    if fallback == "judge":
        assert record["output"] == "B"
        assert combine["chosen"] == ["member_3"]
        assert combine["built"] is False
        assert combine["judge"] == {"raw": "member_3", "returns": "label", "parsed": "member_3"}
        assert combine["presentation_order"] == "author"
        assert combine["result"] == {
            "member_id": "member_3",
            "value": "b",
            "status": "answered",
            "reason": None,
        }
    else:
        assert record["output"] == "C written"
        assert combine["chosen"] == []
        assert combine["built"] is True
        assert combine["judge"] is None
        assert combine["presentation_order"] is None
        assert combine["result"] == {
            "member_id": None,
            "value": "c written",
            "status": "answered",
            "reason": None,
        }
