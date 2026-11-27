"""A ``select="all"`` Router in Unit 5.2: decided purely, never executed (contracts C4, C5, C6).

FEATURE: Router Recipe extension. ADMIT accepts a subset Router and preflights every Model it
names; DECIDE writes its C6 decision as for any Router. Its panel and record belong to Unit 6, so
OPEN refuses to open any member of a selected subset and JOIN refuses to publish it.

INVARIANT (C4): a selected subset makes no Model call and publishes no C5 record here; only a
contract error reaches the caller.
"""

from __future__ import annotations

import json

import pytest
from router_support import (
    ROUTER,
    SELECTOR_MODEL,
    accepted,
    answered,
    case,
    rows,
    step,
    subset_definition,
    text,
)

from screamingface_engine.world.router_decide import decide, open_branch
from screamingface_engine.world.router_join import join
from screamingface_engine.world.router_steps import StepCall
from url4.core.errors import ResolutionError

_BINDING = {"binding": ROUTER}
_ADMIT = accepted(subset_definition())
_REPLY = "code, math"
_SELECTOR = answered("selector_1", SELECTOR_MODEL, _REPLY)


def _decided() -> str:
    """DECIDE of the subset Router whose selector named two candidates, in the current Case."""
    step("admit", _ADMIT)
    return decide(StepCall(text({"admit": _ADMIT, "evidence": rows(_REPLY)}), "", _BINDING))


def test_a_subset_is_decided_purely_with_every_selected_candidate() -> None:
    with case(*_SELECTOR) as recorded:
        draft = json.loads(_decided())

    assert (draft["outcome"], draft["reason"], draft["selected"]) == ("selected", "exact", [1, 2])
    assert recorded == []


@pytest.mark.parametrize("slot", ["c0", "c1", "c2", "default", "panel"])
def test_open_refuses_every_slot_of_a_selected_subset(slot: str) -> None:
    with case(*_SELECTOR), pytest.raises(ResolutionError) as raised:
        open_branch(StepCall(_decided(), slot, {}))

    assert raised.value.code == "benchmark_contract_error"


def test_join_refuses_a_selected_subset_and_publishes_nothing() -> None:
    with case(*_SELECTOR) as recorded, pytest.raises(ResolutionError) as raised:
        # WHY only ``panel``: a subset's JOIN context names its panel slot, not one per candidate.
        context = text({"admit": _ADMIT, "decision": _decided(), "panel": "[]"})
        join(StepCall(context, "", _BINDING))

    assert raised.value.code == "benchmark_contract_error"
    assert [call for call in recorded if call.router is not None] == []
