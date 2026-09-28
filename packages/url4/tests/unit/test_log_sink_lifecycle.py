"""The real DAG executor owns binding, inheritance and revocation."""

import asyncio
import subprocess
import sys

import pytest

from url4.dag import run
from url4.io.static import StaticIOLayer
from url4.observe import Log, NodeFinished, NodeStarted, current_log_sink


class Recorder:
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)

    @property
    def logs(self):
        return [e for e in self.events if isinstance(e, Log)]


class AsyncNode:
    deps: dict = {}

    def __init__(self, action):
        self.action = action

    async def resolve(self, inputs, ctx):
        return await self.action(ctx)


@pytest.mark.asyncio
async def test_no_observer_has_no_sink():
    async def action(ctx):
        assert current_log_sink() is None
        ctx.log("custom", "silent", attributes={"count": 1})
        return "ok"

    assert current_log_sink() is None
    assert await run(AsyncNode(action), StaticIOLayer()) == "ok"


@pytest.mark.asyncio
async def test_concurrent_runs_have_distinct_spans_and_expire_retained_sinks():
    rec = Recorder()
    retained = []
    barrier = asyncio.Barrier(2)

    async def action(ctx):
        sink = current_log_sink()
        assert sink is not None
        retained.append(sink)
        await barrier.wait()
        sink("body", {"count": 1})
        return "ok"

    assert await asyncio.gather(
        *(run(AsyncNode(action), StaticIOLayer(), observer=rec) for _ in range(2))
    ) == ["ok", "ok"]
    assert len({e.span_id for e in rec.logs}) == 2
    starts = {e.span_id for e in rec.events if isinstance(e, NodeStarted)}
    assert {e.span_id for e in rec.logs} == starts
    for sink in retained:
        sink("late")
    assert len(rec.logs) == 2
    assert current_log_sink() is None


@pytest.mark.asyncio
async def test_child_task_inherits_active_sink_but_cannot_use_expired_binding():
    rec = Recorder()
    release = asyncio.Event()
    emitted = asyncio.Event()
    children = []

    async def child():
        sink = current_log_sink()
        assert sink is not None
        sink("during")
        emitted.set()
        await release.wait()
        assert current_log_sink() is None
        sink("after")

    async def action(ctx):
        children.append(asyncio.create_task(child()))
        await emitted.wait()
        return "ok"

    await run(AsyncNode(action), StaticIOLayer(), observer=rec)
    release.set()
    await asyncio.gather(*children)
    assert [e.body for e in rec.logs] == ["during"]


@pytest.mark.asyncio
@pytest.mark.parametrize("observed", [False, True])
async def test_nested_execution_binds_or_inherits_then_restores_outer(observed):
    rec = Recorder()
    retained = []

    async def inner(ctx):
        sink = current_log_sink()
        assert sink is not None
        retained.append(sink)
        sink("inner")
        return "inner"

    async def outer(ctx):
        sink = current_log_sink()
        assert sink is not None
        sink("before")
        await run(AsyncNode(inner), StaticIOLayer(), observer=rec if observed else None)
        assert current_log_sink() is sink
        assert (retained[0] is sink) is (not observed)
        sink("after")
        return "outer"

    await run(AsyncNode(outer), StaticIOLayer(), observer=rec)
    before, inside, after = rec.logs
    assert before.span_id == after.span_id
    assert (inside.span_id == before.span_id) is (not observed)
    assert len([e for e in rec.events if isinstance(e, NodeStarted)]) == (2 if observed else 1)
    retained[0]("expired")
    assert len(rec.logs) == 3


@pytest.mark.asyncio
async def test_off_thread_submission_is_dropped_even_with_copied_context():
    rec = Recorder()

    async def action(ctx):
        sink = current_log_sink()
        assert sink is not None
        await asyncio.to_thread(sink, "off thread")
        sink("on thread")
        return "ok"

    await run(AsyncNode(action), StaticIOLayer(), observer=rec)
    assert [e.body for e in rec.logs] == ["on thread"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_and_cancellation_revoke_sink_preserving_original_error(cancel):
    rec = Recorder()
    retained = []
    entered = asyncio.Event()
    error = RuntimeError("original node failure")

    async def action(ctx):
        sink = current_log_sink()
        assert sink is not None
        retained.append(sink)
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        raise error

    task = asyncio.create_task(run(AsyncNode(action), StaticIOLayer(), observer=rec))
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError) as caught:
        await task
    if not cancel:
        assert caught.value is error
    retained[0]("late")
    assert rec.logs == []
    finishes = [e for e in rec.events if isinstance(e, NodeFinished)]
    assert finishes[0].status == ("cancelled" if cancel else "error")
    assert current_log_sink() is None


@pytest.mark.asyncio
async def test_safe_sink_does_not_swallow_observer_cancellation():
    class CancelObserver:
        def on_event(self, event):
            if isinstance(event, Log):
                raise asyncio.CancelledError()

    async def action(ctx):
        sink = current_log_sink()
        assert sink is not None
        sink("body")
        pytest.fail("cancellation swallowed")

    with pytest.raises(asyncio.CancelledError):
        await run(AsyncNode(action), StaticIOLayer(), observer=CancelObserver())


def test_observation_import_stays_free_of_frameworks():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import url4.observe; "
            "assert not any(n.split('.')[0] in {'pydantic', 'fastapi', 'opentelemetry', "
            "'screamingface_engine'} for n in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_sink_is_expired_before_terminal_observation(fails):
    retained = []

    class TerminalObserver(Recorder):
        def on_event(self, event):
            super().on_event(event)
            if isinstance(event, NodeFinished):
                assert current_log_sink() is None
                retained[0]("too late")

    async def action(ctx):
        sink = current_log_sink()
        assert sink is not None
        retained.append(sink)
        if fails:
            raise RuntimeError("node error")
        return "ok"

    rec = TerminalObserver()
    if fails:
        with pytest.raises(RuntimeError, match="node error"):
            await run(AsyncNode(action), StaticIOLayer(), observer=rec)
    else:
        await run(AsyncNode(action), StaticIOLayer(), observer=rec)
    assert rec.logs == []


@pytest.mark.asyncio
async def test_observed_subtree_restores_outer_sink_after_failure():
    rec = Recorder()
    retained = []

    async def inner(ctx):
        sink = current_log_sink()
        assert sink is not None
        retained.append(sink)
        sink("inner")
        raise RuntimeError("inner error")

    async def outer(ctx):
        sink = current_log_sink()
        assert sink is not None
        with pytest.raises(RuntimeError, match="inner error"):
            await ctx.execute_node(AsyncNode(inner), ctx.scope)
        assert current_log_sink() is sink
        retained[0]("expired inner")
        sink("outer")
        return "ok"

    await run(AsyncNode(outer), StaticIOLayer(), observer=rec)
    assert [e.body for e in rec.logs] == ["inner", "outer"]
    assert rec.logs[0].span_id != rec.logs[1].span_id
    starts = [e for e in rec.events if isinstance(e, NodeStarted)]
    assert starts[1].parent_span_id == starts[0].span_id
