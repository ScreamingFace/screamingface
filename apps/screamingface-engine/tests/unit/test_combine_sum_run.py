"""A Pick that reads a declared sum runs end to end offline (E4b part 6, unit 2; SA#13).

FEATURE: a Candidate that the SDK compiles with ``signals={"risk": sf.Sum({...}), ...}`` runs
offline in the Engine world. Each member gets risk = 0.5 x sev_a + 0.3 x sev_b; the Pick keeps
the member with the lowest risk.
STORY: as a benchmark author, I keep the member answer with the lowest summed severity; a member
that states no B severity has no risk and is excluded.
INVARIANT defended: a sum adds no model call (exactly the three member calls); a missing component
gives a missing sum (``no_signal``); the evidence records the sum like any declared signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"
_MEMBERS = ("prov/alpha", "prov/beta", "prov/gamma")
# Fixture S of the signal-sum PRD §3 and its hand-computed rows (SM-2).
_TEXTS = ("A: 4\nB: 10\nThe answer is 9", "A: 2\nB: 5\nSo 9", "A: 6\nI get 12")
_SIGNALS: list[dict[str, Any]] = [
    {"risk": 5.0, "sev_a": 4.0, "sev_b": 10.0},
    {"risk": 2.5, "sev_a": 2.0, "sev_b": 5.0},
    {"risk": None, "sev_a": 6.0, "sev_b": None},
]
_DECLARED = {
    "risk": {"source": "sum", "coefficients": {"sev_a": 0.5, "sev_b": 0.3}},
    "sev_a": {"source": "verbalized", "pattern": "A: ([0-9]+)"},
    "sev_b": {"source": "verbalized", "pattern": "B: ([0-9]+)"},
}


def _candidate(name: str) -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = _DATA / name
    assert path.exists(), f"combine_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


@pytest.mark.asyncio
async def test_engine_runs_the_sum_pick_fixture_offline() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _candidate("sum_pick_candidate.url4"),
        {model: (text, "0.001") for model, text in zip(_MEMBERS, _TEXTS, strict=True)},
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "A: 2\nB: 5\nSo 9"
    assert record.get("abstained", False) is False
    # exactly three calls: a sum adds no call
    assert sorted(request["model"] for request in seen) == list(_MEMBERS)
    combine = operation(record, "op_synthesis_1")["combine"]
    members = combine["members"]
    assert [member["signals"] for member in members] == _SIGNALS
    assert [list(member["signals"]) for member in members] == [["risk", "sev_a", "sev_b"]] * 3
    assert [(member["status"], member["reason"]) for member in members] == [
        ("answered", None),
        ("answered", None),
        ("excluded", "no_signal"),
    ]
    assert combine["chosen"] == ["member_2"]
    assert combine["signal"] == {"key": "risk", "order": "min"}
    assert combine["declared"] == _DECLARED
    assert combine["result"]["member_id"] == "member_2"
    assert combine["result"]["status"] == "answered"
