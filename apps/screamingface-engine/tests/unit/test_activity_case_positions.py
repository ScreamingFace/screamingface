import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.observations import ModelCall, RunObservations


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_model_records_carry_explicit_selected_position(enabled):
    events = []
    run = RunObservations((lambda: ActivityObserver(enabled=enabled),))
    with run.bind(), case_scope("42", position=(1, 100)):
        async with ModelCall(
            "provider/model", lambda body, attributes=None, **kw: events.append(attributes)
        ) as call:
            call.retry(attempt=2, delay_seconds=0)
    await run.aclose()
    assert len(events) == (3 if enabled else 0)
    assert all(
        event["sf.activity.case_position"] == 1 and event["sf.activity.case_count"] == 100
        for event in events
    )


@pytest.mark.asyncio
async def test_stages_carry_the_same_position_as_nested_model_calls():
    from screamingface_engine.activity.contract import ActivityKind

    # The stage wrapper emits through the current URL4 sink; direct observer scopes
    # exercise the same producer without an external transport.
    events = []
    observer = ActivityObserver()
    run = RunObservations((lambda: observer,))

    def emit(body, attributes=None, **kw):
        events.append(attributes)

    with run.bind(), case_scope("007", position=(2, 100)):
        stage = observer.stage(ActivityKind.ANSWERING, emit)
        assert stage is not None
        async with stage:
            async with ModelCall("provider/model", emit):
                pass
    await run.aclose()
    assert len(events) == 4
    assert all(event["sf.activity.case_position"] == 2 for event in events)
