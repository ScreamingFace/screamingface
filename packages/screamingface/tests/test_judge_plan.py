"""sf.Judge compiles through the reducer plan like every other reducer (OME-1289, 8S F2)."""

from __future__ import annotations

from types import MappingProxyType

from _combine_flow_fixtures import RUBRIC

import screamingface as sf
from screamingface.judge import judge_intent
from screamingface.reducer import Reducer, _ModelSignal, _Step, _Steps


def test_judge_builds_a_reducer_plan() -> None:
    assert not hasattr(sf.Judge, "_steps")
    assert not hasattr(sf.Judge, "_kind")
    assert not hasattr(sf.Judge, "_reducer")
    assert not hasattr(Reducer, "_signals")

    plan = sf.Judge("provider/j", returns="label", rubric=RUBRIC)._plan()

    assert plan.signal_calls == (
        _ModelSignal("judge", "provider/j", judge_intent("label", RUBRIC), MappingProxyType({})),
    )
    assert plan.steps == _Steps(reduce=_Step("label"), select=_Step("by_label"))
