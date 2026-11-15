"""A combine gate sits on any reducer that answers (E4c, OME-1291, gate GT-6, GT-20, P3).

FEATURE: gate row GT#17 (the Engine accepts and runs a gate on a median with a mean observe); the
PIN row GT#18 is the edited GR#4 test in ``test_combine_gate_words.py``.
STORY: as a researcher, ``sf.Fanout(ms, signals=...) >> sf.Gate(when=sf.signal("conf").mean() >= 80,
then=sf.Median(), otherwise=...)`` decides on the median's own combine call.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import parse_spec

_CONF = {"pattern": "Confidence: ([0-9]+)", "source": "verbalized"}


def _median(gate: dict[str, Any]) -> dict[str, Any]:
    spec = vote_spec(
        3,
        reducer="median",
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "median@1", "args": {}},
        select={"op": "nearest@1", "args": {}},
    )
    return {**spec, "signals": {"conf": dict(_CONF)}, "gate": gate}


@pytest.mark.parametrize(("confidence", "branch"), [(90, "majority"), (40, "fallback")])
def test_engine_accepts_a_gate_on_a_median_with_mean_observe(confidence: int, branch: str) -> None:
    gate = {"cmp": ">=", "observe": "mean:conf", "otherwise": "abstain", "threshold": 80}
    spec = _median(gate)
    assert parse_spec(spec_text(spec)).gate is not None
    texts = [f"Confidence: {confidence}\n{value}" for value in ("3", "5", "4")]
    outcome = run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)
    assert outcome.evidence is not None
    evidence = outcome.evidence.model_dump(mode="json", by_alias=True)

    assert evidence["gate"]["branch"] == branch
    assert evidence["gate"]["observed"] == float(confidence)
    if branch == "majority":
        assert outcome.output == f"Confidence: {confidence}\n4"  # the nearest member's text
    else:
        assert evidence["result"] == {
            "member_id": None,
            "value": None,
            "status": "abstain",
            "reason": "gate_not_met",
        }


def test_a_chosen_gate_needs_a_reducer_that_chooses_one_member() -> None:
    gate = {"cmp": ">=", "observe": "chosen:conf", "otherwise": "abstain", "threshold": 80}
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(spec_text(_median(gate)))
    assert "chooses one member" in str(caught.value)
    assert json.dumps(gate) not in str(caught.value)
