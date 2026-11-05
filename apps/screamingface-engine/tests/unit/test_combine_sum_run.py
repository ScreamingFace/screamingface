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


# ---- E4b part 6 unit 5 (band-api): BA#8 ----

_BAND_FIXTURE = "gate_band_vote_candidate.url4"
_BAND_MEMBERS = ("prov/alpha", "prov/beta", "prov/gamma")
_BAND_TALLY = [
    {"value": "yes", "score": 2.0, "holders": ["member_1", "member_2"]},
    {"value": "no", "score": 1.0, "holders": ["member_3"]},
]
_BAND_DECLARED = {
    "risk": {"source": "sum", "coefficients": {"sev_a": 0.5, "sev_b": 0.3}},
    "sev_a": {"source": "verbalized", "pattern": "A: ([0-9]+)"},
    "sev_b": {"source": "verbalized", "pattern": "B: ([0-9]+)"},
}
_BAND_GATE_KEYS = [
    "observe",
    "observed",
    "cmp",
    "threshold",
    "passed",
    "branch",
    "otherwise",
    "abstain_band",
]
# run -> (member texts, Case output, abstained, member signals, gate record, result)
_BAND_RUNS: dict[
    str,
    tuple[
        tuple[str, str, str],
        str,
        bool,
        list[dict[str, float]],
        dict[str, Any],
        dict[str, Any],
    ],
] = {
    "in_band": (
        ("A: 4\nB: 10\nyes", "A: 2\nB: 5\nyes", "A: 1\nB: 5\nno"),
        "",
        True,
        [
            {"risk": 5.0, "sev_a": 4.0, "sev_b": 10.0},
            {"risk": 2.5, "sev_a": 2.0, "sev_b": 5.0},
            {"risk": 2.0, "sev_a": 1.0, "sev_b": 5.0},
        ],
        {
            "observe": "mean:risk",
            "observed": 3.1666666666666665,
            "cmp": "<=",
            "threshold": 3.0,
            "passed": None,
            "branch": "band",
            "otherwise": "abstain",
            "abstain_band": [2.5, 3.5],
        },
        {"member_id": None, "value": None, "status": "abstain", "reason": "in_band"},
    ),
    "below_band": (
        ("A: 2\nB: 0\nyes", "A: 2\nB: 0\nyes", "A: 4\nB: 0\nno"),
        "A: 2\nB: 0\nyes",
        False,
        [
            {"risk": 1.0, "sev_a": 2.0, "sev_b": 0.0},
            {"risk": 1.0, "sev_a": 2.0, "sev_b": 0.0},
            {"risk": 2.0, "sev_a": 4.0, "sev_b": 0.0},
        ],
        {
            "observe": "mean:risk",
            "observed": 1.3333333333333333,
            "cmp": "<=",
            "threshold": 3.0,
            "passed": True,
            "branch": "majority",
            "otherwise": "abstain",
            "abstain_band": [2.5, 3.5],
        },
        {"member_id": "member_1", "value": "yes", "status": "answered", "reason": None},
    ),
}


def _band_candidate() -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = Path(__file__).parent / "data" / "combine_contract" / _BAND_FIXTURE
    assert path.exists(), f"combine_contract/{_BAND_FIXTURE} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("run", ["in_band", "below_band"])
async def test_engine_runs_the_band_fixture_offline(run: str) -> None:
    texts, output, abstained, signals, gate, result = _BAND_RUNS[run]
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _band_candidate(),
        {model: (text, "0.001") for model, text in zip(_BAND_MEMBERS, texts, strict=True)},
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == output
    assert record.get("abstained", False) is abstained
    # exactly three calls: an abstain gate and a sum add no call
    assert sorted(request["model"] for request in seen) == list(_BAND_MEMBERS)
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["gate"] == gate
    assert list(combine["gate"]) == _BAND_GATE_KEYS
    assert combine["result"] == result
    assert combine["tally"] == _BAND_TALLY
    assert combine["agreement"] == 0.6666666666666666
    assert combine["chosen"] == ([] if abstained else ["member_1"])
    assert combine["built"] is False
    assert [member["signals"] for member in combine["members"]] == signals
    assert combine["declared"] == _BAND_DECLARED
