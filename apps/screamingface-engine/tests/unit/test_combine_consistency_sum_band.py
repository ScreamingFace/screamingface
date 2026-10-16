"""Part 6 and part 7 together: a sum and a band read a consistency value (restack, 2026-10-16).

FEATURE: part 6 (``{"source": "sum"}``, ``gate.abstain_band``) and part 7
(``{"source": "consistency"}``) were built in parallel from the same base. After the restack of
part 7 on part 6, one spec can declare both.
STORY: as a benchmark author, I write ``signals={"cons": sf.Consistency(n=4), "risk":
sf.Sum({"cons": 3.0})}`` and gate on ``"mean:cons"`` or ``"mean:risk"`` with an abstain band.
INVARIANT defended: a sum may add a consistency name. The core computes every consistency value
(from the ``samples`` counts) before any sum (the two-pass ``_signal_values``), so the sum sees the
value; a missing consistency value gives a missing sum (SU-I3). A band gate reads a consistency
mean like any declared mean. The evidence writes ``consistency`` directly before ``declared`` and
``gate`` directly after it. Every oracle is hand-computed from fixtures V and W
(``combine_consistency_support``), never copied from the code's output.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_consistency_support import (
    V_ENTRY,
    V_OUTPUTS,
    V_RECORD,
    V_SAMPLES,
    W_ENTRY,
    W_OUTPUTS,
    W_RECORD,
    W_SAMPLES,
    context,
    outcome,
    v_spec,
    wire,
)
from combine_signal_support import argmax_spec

# Fixture V values of cons: member_1 2/4, member_2 2/2, member_3 no value (every sample failed).
# Fixture W values of cons: member_1 2/3, member_2 0/3, member_3 3/3.
T = 0.6666666666666666


def _sum(coefficients: dict[str, float]) -> dict[str, Any]:
    return {"source": "sum", "coefficients": coefficients}


def _band_gate(observe: str, threshold: float, band: list[float]) -> dict[str, Any]:
    return {
        "observe": observe,
        "cmp": ">=",
        "threshold": threshold,
        "otherwise": "abstain",
        "abstain_band": band,
    }


# --- (a) a sum adds a consistency value --------------------------------------------------------


def test_a_sum_adds_the_consistency_value_of_each_member() -> None:
    # risk = 3 x cons: 3 x 0.5 = 1.5, 3 x 1.0 = 3.0; member_3 has no cons, so no risk (SU-I3).
    signals = {"cons": V_ENTRY, "risk": _sum({"cons": 3.0})}
    result = outcome(v_spec(signals=signals), context(outputs=V_OUTPUTS, samples=V_SAMPLES))
    data = wire(result)

    assert result.output == "so 12"
    assert [m["signals"] for m in data["members"]] == [
        {"cons": 0.5, "risk": 1.5},
        {"cons": 1.0, "risk": 3.0},
        {"cons": None, "risk": None},
    ]
    assert data["consistency"] == {"cons": V_RECORD}
    assert data["declared"] == signals


def test_a_pick_reads_a_sum_of_a_consistency_value() -> None:
    # risk = -1 x cons: -2/3, 0.0 (never -0.0), -1.0. The lowest risk is member_3 ("A").
    signals = {"cons": W_ENTRY, "risk": _sum({"cons": -1.0})}
    spec = {**argmax_spec(3, "risk", "min"), "signals": signals}
    result = outcome(spec, context(outputs=W_OUTPUTS, samples=W_SAMPLES))
    data = wire(result)

    assert result.output == "A"
    assert data["chosen"] == ["member_3"]
    assert data["signal"] == {"key": "risk", "order": "min"}
    assert [m["signals"]["risk"] for m in data["members"]] == [-T, 0.0, -1.0]
    assert str(data["members"][1]["signals"]["risk"]) == "0.0"
    assert data["consistency"] == {"cons": W_RECORD}


# --- (b) a band gate reads mean:<consistency name> ----------------------------------------------


@pytest.mark.parametrize(
    ("threshold", "band", "passed", "branch", "status", "reason", "output"),
    [
        # mean:cons = (0.5 + 1.0) / 2 = 0.75 (member_3 has no value): inside [0.7, 0.8].
        (0.9, [0.7, 0.8], None, "band", "abstain", "in_band", ""),
        # outside [0.8, 0.9]: the gate compares 0.75 >= 0.9, false, so gate_not_met.
        (0.9, [0.8, 0.9], False, "fallback", "abstain", "gate_not_met", ""),
        # outside [0.8, 0.9]: 0.75 >= 0.7 holds, so the majority answer.
        (0.7, [0.8, 0.9], True, "majority", "answered", None, "so 12"),
    ],
    ids=["in-band", "fallback", "majority"],
)
def test_a_band_gate_reads_the_consistency_mean(
    threshold: float,
    band: list[float],
    passed: bool | None,
    branch: str,
    status: str,
    reason: str | None,
    output: str,
) -> None:
    gate = _band_gate("mean:cons", threshold, band)
    result = outcome(v_spec(gate=gate), context(outputs=V_OUTPUTS, samples=V_SAMPLES))
    data = wire(result)

    assert data["gate"] == {
        "observe": "mean:cons",
        "observed": 0.75,
        "cmp": ">=",
        "threshold": threshold,
        "passed": passed,
        "branch": branch,
        "otherwise": "abstain",
        "abstain_band": band,
    }
    assert result.output == output
    assert data["result"]["status"] == status
    assert data["result"]["reason"] == reason
    assert data["consistency"] == {"cons": V_RECORD}


def test_a_band_gate_reads_the_mean_of_a_sum_of_a_consistency_value() -> None:
    # risk = 3 x cons: 1.5, 3.0, none. mean:risk = 2.25, inside [2.0, 2.5]: in_band.
    signals = {"cons": V_ENTRY, "risk": _sum({"cons": 3.0})}
    gate = _band_gate("mean:risk", 3.0, [2.0, 2.5])
    result = outcome(
        v_spec(signals=signals, gate=gate), context(outputs=V_OUTPUTS, samples=V_SAMPLES)
    )
    data = wire(result)

    assert data["gate"]["observed"] == 2.25
    assert data["gate"]["branch"] == "band"
    assert data["gate"]["passed"] is None
    assert data["result"]["status"] == "abstain"
    assert data["result"]["reason"] == "in_band"
    assert result.output == ""
    assert data["consistency"] == {"cons": V_RECORD}


# --- (d) the key order of the two new optional keys ---------------------------------------------


def test_the_evidence_writes_consistency_declared_then_gate_with_its_band_last() -> None:
    gate = _band_gate("mean:cons", 0.9, [0.7, 0.8])
    data = wire(outcome(v_spec(gate=gate), context(outputs=V_OUTPUTS, samples=V_SAMPLES)))

    keys = list(data)
    at = keys.index("consistency")
    assert keys[at : at + 3] == ["consistency", "declared", "gate"]
    assert list(data["gate"]) == [
        "observe",
        "observed",
        "cmp",
        "threshold",
        "passed",
        "branch",
        "otherwise",
        "abstain_band",
    ]
