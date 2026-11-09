"""A verbalized vote runs end to end: the SDK fixture, the mocked gateway and the run record.

FEATURE: a Candidate that the SDK compiles with ``sf.Verbalized`` runs offline in the Engine world
and weights each member answer by the confidence the member wrote (E4b part 3, unit 2; VB#8).
STORY: as a benchmark author, I ask three models for an answer and a confidence, and the vote
gives the most confident answer the most weight, with no extra model call for the signal.
INVARIANT defended: the signal costs no model call (the run makes exactly the member calls); the
run record carries the read key, the weights and the declared map that the spec wrote (EV-I2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"
# The SDK-compiled fixture of this unit (E7); the SDK drift guard keeps it byte-equal.
_FIXTURE = "verbalized_vote_candidate.url4"


def _candidate() -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = _DATA / _FIXTURE
    assert path.exists(), f"combine_contract/{_FIXTURE} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


@pytest.mark.asyncio
async def test_vote_weighted_by_verbalized_confidence() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _candidate(),
        {
            "prov/alpha": ("Confidence: 90\nA", "0.001"),
            "prov/beta": ("Confidence: 60\nB", "0.001"),
            "prov/gamma": ("Confidence: 30\nA", "0.001"),
        },
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "Confidence: 90\nA"
    assert len(seen) == 3
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["tally"] == [
        {"value": "a", "score": 120.0, "holders": ["member_1", "member_3"]},
        {"value": "b", "score": 60.0, "holders": ["member_2"]},
    ]
    assert combine["chosen"] == ["member_1"]
    assert [m["weight"] for m in combine["members"]] == [90.0, 60.0, 30.0]
    assert [m["signals"] for m in combine["members"]] == [
        {"conf": 90.0},
        {"conf": 60.0},
        {"conf": 30.0},
    ]
    assert combine["signal"] == {"key": "conf", "order": None}
    assert combine["declared"] == {
        "conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}
    }
