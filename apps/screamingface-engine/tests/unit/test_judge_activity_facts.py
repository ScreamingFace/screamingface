"""Judge attribution follows explicit task/run scope and uses closed public facts."""

import pytest

from screamingface_engine.activity.contract import safe_fact
from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.grading_call_scope import grading_call_scope
from screamingface_engine.observations import ModelCall, RunObservations


@pytest.mark.asyncio
async def test_judge_identity_does_not_inherit_a_different_case_position_or_child_run():
    records = []

    def emit(body, attributes=None, **kwargs):
        records.append(attributes)

    outer = RunObservations((ActivityObserver,))
    inner = RunObservations((ActivityObserver,))
    try:
        with outer.bind(), case_scope(1, position=(1, 2)), grading_call_scope(2):
            async with ModelCall("judge", emit):
                pass
            with inner.bind():
                async with ModelCall("nested-run", emit):
                    pass
        with outer.bind():
            async with ModelCall("outside", emit):
                pass
    finally:
        await inner.aclose()
        await outer.aclose()
    judge = [r for r in records if r["sf.activity.model_id"] == "judge"]
    assert len(judge) == 2
    assert all(r["sf.activity.case_id"] == 2 and r["sf.activity.role"] == "judge" for r in judge)
    assert all("sf.activity.case_position" not in r for r in judge)
    other = [r for r in records if r["sf.activity.model_id"] != "judge"]
    assert all("sf.activity.case_id" not in r and "sf.activity.role" not in r for r in other)


@pytest.mark.parametrize("name,value", [("role", "judge"), ("action", "recording")])
def test_activity_semantics_are_closed_allowlists(name, value):
    assert safe_fact(name, value) == value
    with pytest.raises(ValueError):
        safe_fact(name, "PRIVATE PROMPT")


def test_absent_policy_enables_observation_but_explicit_off_does_not():
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.observation_plugins import observation_factories

    with RunObservations(observation_factories({})).bind():
        assert current_session() is not None
    with RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "off"})).bind():
        assert current_session() is None
