"""The engine observation seam: RunStarted/NodeStarted/NodeFinished/RunFinished
emitted to an injected :class:`~url4.observe.Observer`, plus the two escape
hatches nodes reach for (``ctx.report_usage``, ``ctx.log``).

Every test drives the real :func:`~url4.dag.run` against a
:class:`~url4.io.static.StaticIOLayer` world — no mocking of the executor
itself, so these tests exercise the actual scheduling/memoization path.
"""

from __future__ import annotations

import json

import pytest

from url4.core.errors import ResolutionError
from url4.dag import run
from url4.dag.node import DagNode
from url4.io.static import StaticIOLayer
from url4.observe import (
    Log,
    NodeFinished,
    NodeStarted,
    ObservationEvent,
    RunFinished,
    RunStarted,
    Usage,
)


class RecordingObserver:
    """Collects every emitted event, in emission order."""

    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


class _BoomNode:
    """A hand-built node that always fails with a permanent error."""

    deps: dict = {}

    async def resolve(self, inputs, ctx):
        raise ResolutionError("boom", code="custom_code", permanent=True)


class _UsageNode:
    """A hand-built node that reports token usage through ``ctx``."""

    deps: dict = {}

    async def resolve(self, inputs, ctx):
        ctx.report_usage(provider="anthropic", model="claude-x", input_tokens=10, output_tokens=5)
        return "ok"


class _LoggingNode:
    """A hand-built node that logs through ``ctx``."""

    deps: dict = {}

    async def resolve(self, inputs, ctx):
        ctx.log("info", "hello from the node")
        return "ok"


class _RaisingOnNodeStarted:
    """An observer whose ``on_event`` raises on the first ``NodeStarted`` it sees."""

    def __init__(self) -> None:
        self.error = RuntimeError("observer-boom")

    def on_event(self, event: ObservationEvent) -> None:
        if isinstance(event, NodeStarted):
            raise self.error


@pytest.mark.asyncio
async def test_run_emits_started_node_pairs_then_finished_in_order() -> None:
    # Behavior 1: RunStarted -> (NodeStarted/NodeFinished pairs) -> RunFinished.
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    rec = RecordingObserver()
    result = await run("https://a!go", io, observer=rec)
    assert result == "go\n\nA"

    assert isinstance(rec.events[0], RunStarted)
    assert isinstance(rec.events[-1], RunFinished)
    assert rec.events[-1].status == "ok"

    open_spans: set[str] = set()
    for event in rec.events[1:-1]:
        assert isinstance(event, (NodeStarted, NodeFinished))
        if isinstance(event, NodeStarted):
            open_spans.add(event.span_id)
        else:
            assert event.span_id in open_spans
            open_spans.discard(event.span_id)
    assert not open_spans  # every started span finished
    assert any(isinstance(e, NodeStarted) for e in rec.events)


@pytest.mark.asyncio
async def test_run_without_observer_is_behaviorally_unchanged() -> None:
    # Behavior 2: no observer -> identical result AND identical error behavior.
    baseline = await run("https://a!go", StaticIOLayer(fetch_map={"https://a": "A"}))
    observed = await run("https://a!go", StaticIOLayer(fetch_map={"https://a": "A"}), observer=None)
    assert observed == baseline

    with pytest.raises(ResolutionError) as exc_baseline:
        await run("https://missing!go", StaticIOLayer())
    with pytest.raises(ResolutionError) as exc_observed:
        await run("https://missing!go", StaticIOLayer(), observer=None)
    assert exc_baseline.value.code == exc_observed.value.code
    assert str(exc_baseline.value) == str(exc_observed.value)


@pytest.mark.asyncio
async def test_diamond_shared_dependency_gets_exactly_one_span_pair() -> None:
    # Behavior 3: a diamond-shared node resolves (and is observed) exactly once.
    io = StaticIOLayer(fetch_map={"https://x": "V"})
    rec = RecordingObserver()
    result = await run("(a=https://x, use $a, also $a)!both: $a", io, observer=rec)
    assert result == "both: V\n\na: V\nuse V\nalso V"

    starts = [e for e in rec.events if isinstance(e, NodeStarted) and e.node_kind == "WebFetchNode"]
    assert len(starts) == 1
    fetch_span = starts[0].span_id
    finishes = [e for e in rec.events if isinstance(e, NodeFinished) and e.span_id == fetch_span]
    assert len(finishes) == 1


@pytest.mark.asyncio
async def test_permanent_error_reports_code_and_permanent_then_propagates() -> None:
    # Behavior 4: a permanent Url4Error -> NodeFinished{error,code,permanent} +
    # RunFinished{error}; the exception still propagates out of run().
    io = StaticIOLayer()
    rec = RecordingObserver()
    with pytest.raises(ResolutionError, match="boom"):
        await run(_BoomNode(), io, observer=rec)

    node_finishes = [e for e in rec.events if isinstance(e, NodeFinished)]
    assert len(node_finishes) == 1
    finished = node_finishes[0]
    assert finished.status == "error"
    assert finished.code == "custom_code"
    assert finished.permanent is True

    run_finishes = [e for e in rec.events if isinstance(e, RunFinished)]
    assert len(run_finishes) == 1
    assert run_finishes[0].status == "error"


@pytest.mark.asyncio
async def test_optional_guard_failure_is_reported_but_run_still_succeeds() -> None:
    # Behavior 5: a guarded optional-failure subtree emits NodeFinished{error}
    # for the failed subtree, and run() still returns a value.
    io = StaticIOLayer()  # no mapping for https://x -> the source fetch fails
    rec = RecordingObserver()
    result = await run("(a=https://x;optional, use $a)!go", io, observer=rec)
    assert result == "go\n\nuse $a"

    errors = [e for e in rec.events if isinstance(e, NodeFinished) and e.status == "error"]
    assert len(errors) >= 1
    run_finishes = [e for e in rec.events if isinstance(e, RunFinished)]
    assert run_finishes[-1].status == "ok"


@pytest.mark.asyncio
async def test_iteration_row_spans_parent_to_the_map_node() -> None:
    # Behavior 6: each row's spawned fragment parents to the MapNode's span_id.
    io = StaticIOLayer(fetch_map={"https://rows": '["a", "b"]'})
    rec = RecordingObserver()
    result = await run("https://rows*()!'T: $item'", io, observer=rec)
    assert json.loads(result) == ["T: a", "T: b"]

    starts = [e for e in rec.events if isinstance(e, NodeStarted)]
    map_start = next(e for e in starts if e.node_kind == "MapNode")
    # MapNode's own "collection" dependency edge (the WebFetchNode for
    # "https://rows") also parents directly to the MapNode span — that's a
    # regular dep, not a spawned row, so it's excluded here by node kind.
    row_roots = [
        e for e in starts if e.parent_span_id == map_start.span_id and e.node_kind != "WebFetchNode"
    ]
    assert len(row_roots) == 2  # one root span per row

    finished_span_ids = {e.span_id for e in rec.events if isinstance(e, NodeFinished)}
    for root in row_roots:
        assert root.span_id in finished_span_ids  # started before it finished


@pytest.mark.asyncio
async def test_observer_that_raises_fails_the_run_with_that_exception() -> None:
    # Behavior 7: no try/except around on_event -> the observer's own exception
    # is what run() fails with.
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    observer = _RaisingOnNodeStarted()
    with pytest.raises(RuntimeError) as exc_info:
        await run("https://a!go", io, observer=observer)
    assert exc_info.value is observer.error


@pytest.mark.asyncio
async def test_report_usage_emits_usage_event_with_current_span() -> None:
    # Behavior 8: ctx.report_usage() during a node's resolve -> a Usage event
    # carrying that node's span_id.
    io = StaticIOLayer()
    rec = RecordingObserver()
    result = await run(_UsageNode(), io, observer=rec)
    assert result == "ok"

    usages = [e for e in rec.events if isinstance(e, Usage)]
    assert len(usages) == 1
    usage = usages[0]
    assert usage.provider == "anthropic"
    assert usage.model == "claude-x"
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5

    node_starts = [e for e in rec.events if isinstance(e, NodeStarted)]
    assert len(node_starts) == 1
    assert usage.span_id == node_starts[0].span_id


@pytest.mark.asyncio
async def test_log_emits_log_event_with_current_span() -> None:
    # Behavior: ctx.log() during a node's resolve -> a Log event carrying that
    # node's span_id and body.
    io = StaticIOLayer()
    rec = RecordingObserver()
    result = await run(_LoggingNode(), io, observer=rec)
    assert result == "ok"

    logs = [e for e in rec.events if isinstance(e, Log)]
    assert len(logs) == 1
    log = logs[0]
    assert log.severity == "info"
    assert log.body == "hello from the node"

    node_starts = [e for e in rec.events if isinstance(e, NodeStarted)]
    assert len(node_starts) == 1
    assert log.span_id == node_starts[0].span_id


_CORPUS: list[str | DagNode] = [
    "https://a!go",
    "(a=https://x, use $a, also $a)!both: $a",
    "(a=https://x;optional, use $a)!go",
    "https://rows*()!'T: $item'",
    _BoomNode(),
    # Multi-level required failure: root ProcessNode depends on the failing
    # WebFetchNode. This is the Fix-1 regression counterexample — without the
    # gather/resolve try split in `_eval`, the ProcessNode ancestor emits
    # NodeStarted but never NodeFinished (it dangles) when its dep fails.
    "https://missing!go",
]

_CORPUS_IO: list[dict[str, str]] = [
    {"https://a": "A"},
    {"https://x": "V"},
    {},
    {"https://rows": '["a", "b"]'},
    {},
    {},
]


@pytest.mark.asyncio
async def test_run_accepts_trace_id_and_root_span_id_overrides() -> None:
    # Deliverable 1: a caller-supplied trace_id/root_span_id is used verbatim (not minted), and
    # the top node's parent_span_id resolves to the supplied root_span_id — this is what lets a
    # hosting service's own run-root identity (e.g. url4-cloud's publish.run) agree with the
    # engine's, so the top-level span's parent equals the run-root for the root-collapse rule.
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    rec = RecordingObserver()
    trace_id = "a" * 32
    root_span_id = "b" * 16

    result = await run(
        "https://a!go", io, observer=rec, trace_id=trace_id, root_span_id=root_span_id
    )
    assert result == "go\n\nA"

    run_started = rec.events[0]
    assert isinstance(run_started, RunStarted)
    assert run_started.trace_id == trace_id
    assert run_started.root_span_id == root_span_id

    node_starts = [e for e in rec.events if isinstance(e, NodeStarted)]
    top_node = next(e for e in node_starts if e.parent_span_id == root_span_id)
    assert top_node is not None


@pytest.mark.asyncio
async def test_node_finished_span_ids_are_a_bijection_with_node_started() -> None:
    # Behavior 10: for a small corpus of representative expressions, every
    # NodeFinished has a matching NodeStarted with the same span_id.
    for expr, fetch_map in zip(_CORPUS, _CORPUS_IO, strict=True):
        io = StaticIOLayer(fetch_map=fetch_map)
        rec = RecordingObserver()
        try:
            await run(expr, io, observer=rec)
        except Exception:
            pass  # some corpus entries intentionally fail; the bijection must still hold

        started_ids = [e.span_id for e in rec.events if isinstance(e, NodeStarted)]
        finished_ids = [e.span_id for e in rec.events if isinstance(e, NodeFinished)]
        assert len(started_ids) == len(set(started_ids)), expr
        assert sorted(started_ids) == sorted(finished_ids), expr


@pytest.mark.asyncio
async def test_relative_node_observes_its_static_path_template() -> None:
    from url4.dag.nodes import RelUrlNode, TextNode

    template = "/private/$case"
    resolved = "/private/42"
    rec = RecordingObserver()

    result = await run(
        RelUrlNode(template, deps={"bind:case": TextNode("42")}),
        StaticIOLayer(fetch_map={resolved: "ok"}),
        observer=rec,
    )

    assert result == "ok"
    started = next(
        e for e in rec.events if isinstance(e, NodeStarted) and e.node_kind == "RelUrlNode"
    )
    assert started.detail == template


@pytest.mark.asyncio
async def test_failing_relative_node_retains_its_route_detail() -> None:
    from url4.dag.nodes import RelUrlNode

    route = "/benchmarks/case-execution"
    rec = RecordingObserver()

    with pytest.raises(ResolutionError, match="no fetch mapping"):
        await run(RelUrlNode(route), StaticIOLayer(), observer=rec)

    started = next(
        e for e in rec.events if isinstance(e, NodeStarted) and e.node_kind == "RelUrlNode"
    )
    assert started.detail == route
    finished = next(
        e for e in rec.events if isinstance(e, NodeFinished) and e.span_id == started.span_id
    )
    assert finished.status == "error"
