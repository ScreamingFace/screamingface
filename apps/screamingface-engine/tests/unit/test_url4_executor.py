from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest

from screamingface_engine.artifacts import ArtifactStore
from screamingface_engine.runner.cache_counters import RunCacheCounters
from screamingface_engine.runner.executor import (
    BRIDGE_HIGH_WATER,
    BRIDGE_SOFT_CAP,
    BridgeOverflowError,
    Url4Executor,
    _Bridge,
    _closing_logs,
    _RunState,
    deny_by_default_world,
)
from screamingface_engine.testing import InMemoryEventStream
from url4.core.errors import ParseError, ResolutionError
from url4.dag.nodes import TextNode
from url4.io.static import StaticIOLayer
from url4.observe import Log, NodeFinished, NodeStarted, ObservationEvent, RunStarted, Usage
from url4.streaming.interfaces import Completed, ExecStep, Traced
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import (
    CostUsageData,
    LogData,
    SpanData,
    StartedEvent,
    TerminatedEvent,
)

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


def _unwrap(frame: object) -> object:
    return frame.payload if isinstance(frame, Traced) else frame


async def _drain(executor: Url4Executor, url4: object) -> list[object]:
    return [frame async for frame in executor.execute(cast("str", url4))]


@pytest.mark.asyncio
async def test_static_world_yields_span_then_completed_with_real_result() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    executor = Url4Executor(io)

    frames = await _drain(executor, "https://a!go")

    last = frames[-1]
    assert isinstance(last, Completed)
    assert last.result.body == "go\n\nA"
    spans = [f for f in frames[:-1] if isinstance(_unwrap(f), SpanData)]
    assert len(spans) >= 1
    assert all(isinstance(f, Traced) and f.span is not None for f in spans)


@pytest.mark.asyncio
async def test_frame_streams_before_the_run_finishes() -> None:
    gate = asyncio.Event()

    async def gated(_context: str, _intent: str) -> str:
        await gate.wait()
        return "GATED"

    io = StaticIOLayer(
        fetch_map={"https://fast": "FAST"},
        routes={"/gated": gated},
    )
    executor = Url4Executor(io)
    gen = executor.execute("(f=https://fast, g=/gated()!go)!'$f $g'")

    first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert not gate.is_set()
    assert not isinstance(first, Completed)

    gate.set()
    frames: list[object] = [first]
    async for frame in gen:
        frames.append(frame)

    last = frames[-1]
    assert isinstance(last, Completed)
    assert last.result.body is not None
    assert "FAST" in last.result.body
    assert "GATED" in last.result.body


@pytest.mark.asyncio
async def test_parse_error_raises_unwrapped_with_no_completed() -> None:
    io = StaticIOLayer()
    executor = Url4Executor(io)

    frames: list[ExecStep] = []
    with pytest.raises(ParseError) as exc_info:
        async for frame in executor.execute("((("):
            frames.append(frame)

    assert not isinstance(exc_info.value, ExceptionGroup)
    assert exc_info.value.code == "malformed_source"
    assert exc_info.value.permanent is True
    assert not any(isinstance(f, Completed) for f in frames)


class _UsageChildNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx) -> str:
        ctx.report_usage(provider="anthropic", model="claude-x", input_tokens=10, output_tokens=5)
        return "child"


class _UsageRootNode:
    def __init__(self) -> None:
        self.deps = {"c": _UsageChildNode()}

    async def resolve(self, inputs, ctx) -> str:
        ctx.report_usage(provider="anthropic", model="claude-y", input_tokens=20, output_tokens=8)
        return f"root:{inputs['c']}"


@pytest.mark.asyncio
async def test_n_usage_reports_sum_into_subtree_cost() -> None:
    executor = Url4Executor(StaticIOLayer())

    frames = await _drain(executor, _UsageRootNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    usage = completed.subtree_cost.usage
    assert usage.input_tokens == 30
    assert usage.output_tokens == 13
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
    assert usage.reasoning_tokens == 0
    cost = completed.subtree_cost.cost
    assert cost.input_usd == cost.output_usd == cost.cache_read_usd == 0
    assert cost.cache_creation_usd == cost.reasoning_usd == 0
    assert cost.total_usd == 0
    assert completed.subtree_cost.pricing_version == "unpriced"


@pytest.mark.asyncio
async def test_zero_usage_still_yields_valid_all_zero_subtree() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    executor = Url4Executor(io)

    frames = await _drain(executor, "https://a!go")

    completed = frames[-1]
    assert isinstance(completed, Completed)
    subtree = completed.subtree_cost
    assert subtree.usage.input_tokens == 0
    assert subtree.usage.output_tokens == 0
    assert subtree.cost.total_usd == 0
    assert subtree.pricing_version == "unpriced"
    assert subtree.provider and subtree.model


class _SingleProviderModelNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx) -> str:
        ctx.report_usage(provider="anthropic", model="claude-x", input_tokens=1, output_tokens=1)
        ctx.report_usage(provider="anthropic", model="claude-x", input_tokens=2, output_tokens=2)
        return "ok"


@pytest.mark.asyncio
async def test_subtree_provider_model_when_all_usage_shares_one_pair() -> None:
    executor = Url4Executor(StaticIOLayer())

    frames = await _drain(executor, _SingleProviderModelNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.subtree_cost.provider == "anthropic"
    assert completed.subtree_cost.model == "claude-x"


@pytest.mark.asyncio
async def test_subtree_provider_model_is_mixed_when_pairs_differ() -> None:
    executor = Url4Executor(StaticIOLayer())

    frames = await _drain(executor, _UsageRootNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.subtree_cost.provider == "mixed"
    assert completed.subtree_cost.model == "mixed"


@pytest.mark.asyncio
async def test_closing_generator_cancels_in_flight_engine_run() -> None:
    gate = asyncio.Event()
    released_ran = False

    async def gated(_context: str, _intent: str) -> str:
        nonlocal released_ran
        await gate.wait()
        released_ran = True
        return "GATED"

    io = StaticIOLayer(
        fetch_map={"https://fast": "FAST"},
        routes={"/gated": gated},
    )
    executor = Url4Executor(io)
    gen = executor.execute("(f=https://fast, g=/gated()!go)!'$f $g'")

    await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    await cast("AsyncGenerator[ExecStep, None]", gen).aclose()
    await asyncio.sleep(0)

    assert released_ran is False
    gate.set()


class _AcloseSpy:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls = 0
        self._raises = raises

    async def __call__(self) -> None:
        self.calls += 1
        if self._raises is not None:
            raise self._raises


@pytest.mark.asyncio
async def test_world_aclose_runs_once_after_a_normal_drain() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    spy = _AcloseSpy()
    executor = Url4Executor(io, world_aclose=spy)

    frames = await _drain(executor, "https://a!go")

    assert isinstance(frames[-1], Completed)
    assert spy.calls == 1


@pytest.mark.asyncio
async def test_world_aclose_runs_once_when_the_run_raises() -> None:
    io = StaticIOLayer()
    spy = _AcloseSpy()
    executor = Url4Executor(io, world_aclose=spy)

    with pytest.raises(ParseError):
        async for _ in executor.execute("((("):
            pass

    assert spy.calls == 1


@pytest.mark.asyncio
async def test_world_aclose_runs_once_on_early_generator_aclose() -> None:
    gate = asyncio.Event()

    async def gated(_context: str, _intent: str) -> str:
        await gate.wait()
        return "GATED"

    io = StaticIOLayer(routes={"/gated": gated})
    spy = _AcloseSpy()
    executor = Url4Executor(io, world_aclose=spy)
    gen = executor.execute("/gated()!go")

    await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    await cast("AsyncGenerator[ExecStep, None]", gen).aclose()
    await asyncio.sleep(0)

    assert spy.calls == 1
    gate.set()


@pytest.mark.asyncio
async def test_world_aclose_failure_does_not_mask_the_run_s_real_error() -> None:
    io = StaticIOLayer()
    spy = _AcloseSpy(raises=RuntimeError("teardown boom"))
    executor = Url4Executor(io, world_aclose=spy)

    with pytest.raises(ParseError):
        async for _ in executor.execute("((("):
            pass

    assert spy.calls == 1


@pytest.mark.asyncio
async def test_no_world_aclose_is_a_no_op() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    executor = Url4Executor(io)

    frames = await _drain(executor, "https://a!go")

    assert isinstance(frames[-1], Completed)


def test_bridge_on_event_drop_policy_never_drops_span_usage_lifecycle() -> None:
    bridge = _Bridge(maxsize=2)
    bridge.on_event(RunStarted("t" * 32, "s" * 16, "hash"))
    bridge.on_event(NodeStarted("span-1", None, "WebFetchNode", ""))
    bridge.on_event(Log("span-1", "INFO", "line-1"))
    bridge.on_event(Log("span-1", "INFO", "line-2"))
    assert bridge.dropped == 2
    assert len(bridge._buf) == 2

    bridge.on_event(NodeFinished("span-1", "ok", 1))
    assert bridge.dropped == 2
    assert len(bridge._buf) == 3

    bridge2 = _Bridge(maxsize=2)
    bridge2.on_event(NodeStarted("span-1", None, "WebFetchNode", ""))
    bridge2.on_event(Log("span-1", "INFO", "kept-until-evicted"))
    bridge2.on_event(NodeFinished("span-1", "ok", 1))
    assert bridge2.dropped == 1
    kinds = [type(e).__name__ for e in bridge2._buf]
    assert "Log" not in kinds
    assert "NodeFinished" in kinds


def test_bridge_raises_on_a_span_only_burst_past_the_hard_cap() -> None:
    # WHY the tiny budget: the hard cap is `budget // EVENT_SIZE_ESTIMATE_BYTES`, so a
    # small budget keeps this unit's burst short instead of buffering the 131 072-event
    # default cap (OME-906).
    bridge = _Bridge(maxsize=2, memory_budget=10_240)
    bridge.on_event(RunStarted("t" * 32, "s" * 16, "hash"))
    bridge.on_event(NodeStarted("span-1", None, "WebFetchNode", ""))
    with pytest.raises(BridgeOverflowError):
        for i in range(bridge._hard_cap):
            bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))


# FEATURE: bound the event bridge by memory, not by event count (OME-906).
#
# The old count cap (`8 x soft cap` = 8 192) was a ceiling on DAG width: the engine fans
# out over `deps` with an unbounded gather and emits each node's `NodeStarted` before it
# awaits anything, so a wide fan-in lands its whole event burst in one event-loop slice,
# before the drain can run at all. These tests pin the budget-bound behaviors the spec
# requires: a wide DAG completes, the bound follows a byte budget, and the error names
# which of the two failure shapes fired.


def test_the_hard_cap_is_derived_from_the_memory_budget() -> None:
    bridge = _Bridge(maxsize=2, memory_budget=10_240)
    assert bridge._hard_cap == 10_240 // 512  # 20 events at 512 B per event


def test_a_producer_that_never_stops_fails_at_the_budget() -> None:
    bridge = _Bridge(maxsize=2, memory_budget=10_240)
    bridge.on_event(RunStarted("t" * 32, "s" * 16, "hash"))
    with pytest.raises(BridgeOverflowError):
        for i in range(25):
            bridge.on_event(NodeStarted(f"span-{i}", None, "TextNode", ""))


@pytest.mark.asyncio
async def test_overflow_with_drain_progress_names_the_budget_not_the_consumer() -> None:
    # A drain count above zero is PROOF the consumer runs: the backlog is one burst that
    # outran the budget, so the message must name the budget and the DAG shape, and must
    # not accuse the consumer (the old message's claim, disproven by measurement).
    bridge = _Bridge(maxsize=2, memory_budget=10_240)
    bridge.on_event(RunStarted("t" * 32, "s" * 16, "hash"))
    events = cast("AsyncGenerator[ObservationEvent, None]", bridge.drain())
    await events.__anext__()  # one event drained: the consumer IS running
    with pytest.raises(BridgeOverflowError) as excinfo:
        for i in range(25):
            bridge.on_event(NodeStarted(f"span-{i}", None, "TextNode", ""))
    await events.aclose()
    message = str(excinfo.value)
    assert "URL4_CLOUD_BRIDGE_MEMORY_BUDGET_BYTES" in message
    assert "DAG" in message
    assert "consumer" not in message


def test_overflow_with_zero_drained_says_the_consumer_never_ran() -> None:
    # Zero drained events is the ONE case where the old accusation was right: the
    # consumer never ran at all, which is a stuck consumer, not a wide DAG.
    bridge = _Bridge(maxsize=2, memory_budget=10_240)
    with pytest.raises(BridgeOverflowError) as excinfo:
        for i in range(25):
            bridge.on_event(NodeStarted(f"span-{i}", None, "TextNode", ""))
    message = str(excinfo.value)
    assert "never drained" in message
    assert "stuck" in message


class _WideFanIn:
    """A node with `width` dependencies: the engine gathers over them unbounded, so the
    whole width's events land in one event-loop slice before the drain can run."""

    def __init__(self, width: int) -> None:
        self.deps: dict[str, TextNode] = {f"dep{i}": TextNode("x") for i in range(width)}

    async def resolve(self, inputs, ctx) -> str:
        return "done"


@pytest.mark.asyncio
async def test_a_wide_dag_burst_completes_instead_of_overflowing() -> None:
    # RED against the count cap: 9 000 deps put ~18 000 events (NodeStarted plus
    # NodeFinished per node) in one slice, past the old hard cap of 8 192, and the run
    # died with BridgeOverflowError. The default budget (64 MiB / 512 B = 131 072
    # events) holds the same burst — a legitimately wide DAG must complete.
    executor = Url4Executor(StaticIOLayer())

    frames = await _drain(executor, _WideFanIn(9_000))

    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body == "done"


class _LoggyNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx) -> str:
        for i in range(20):
            ctx.log("INFO", f"line-{i}")
        return "done"


@pytest.mark.asyncio
async def test_overflow_drops_only_logs_and_reports_dropped_count() -> None:
    executor = Url4Executor(StaticIOLayer(), queue_cap=2)

    frames = await _drain(executor, _LoggyNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body == "done"

    spans = [f for f in frames if isinstance(_unwrap(f), SpanData)]
    assert len(spans) >= 1

    warn_logs = [
        f
        for f in frames
        if isinstance(payload := _unwrap(f), LogData)
        and payload.severity_text == "WARN"
        and "dropped" in payload.body
    ]
    assert len(warn_logs) == 1
    info_logs = [
        f
        for f in frames
        if isinstance(payload := _unwrap(f), LogData) and payload.severity_text == "INFO"
    ]
    assert len(info_logs) < 20


class _WarningNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx) -> str:
        ctx.log("WARN", "custom warning")
        return "ok"


@pytest.mark.asyncio
async def test_surviving_log_event_maps_to_log_data() -> None:
    executor = Url4Executor(StaticIOLayer())

    frames = await _drain(executor, _WarningNode())

    logs = [
        f
        for f in frames
        if isinstance(payload := _unwrap(f), LogData) and payload.body == "custom warning"
    ]
    assert len(logs) == 1
    log = _unwrap(logs[0])
    assert isinstance(log, LogData)
    assert log.severity_number == 13
    assert log.severity_text == "WARN"
    # A log emitted from inside a node is attributed to THAT node's span, not to the run root.
    # This assertion used to require `span is None`, which pinned the defect: the engine supplies
    # `Log.span_id`, the executor discarded it, and every log line on the wire looked as though it
    # came from the run itself — so no consumer could tell which node logged what.
    assert isinstance(logs[0], Traced)
    assert logs[0].span is not None
    span_ids = {
        f.span.span_id
        for f in frames
        if isinstance(f, Traced) and f.span is not None and isinstance(f.payload, SpanData)
    }
    assert logs[0].span.span_id in span_ids


class _LongResultNode:
    deps: dict = {}

    async def resolve(self, inputs, ctx) -> str:
        return "X" * 50


# FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892).
# INVARIANT: no code path emits a truncated body. A result is delivered inline (≤ cap),
# spilled whole to the artifact store (> cap), or the run FAILS with `result_too_large` —
# the truncate-and-still-succeed path of GitHub #642 is unrepresentable.


@pytest.mark.asyncio
async def test_result_at_inline_cap_stays_inline(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    executor = Url4Executor(StaticIOLayer(), result_cap=50, artifact_store=store)

    frames = await _drain(executor, _LongResultNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    # WHY: boundary — exactly-at-cap is the biggest result that must stay byte-identical
    # to the pre-OME-892 wire shape, so old SDKs never notice small runs changed.
    assert completed.result.body == "X" * 50
    assert completed.result.artifact is None


@pytest.mark.asyncio
async def test_over_cap_result_is_spilled_whole_to_the_artifact_store(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    executor = Url4Executor(StaticIOLayer(), result_cap=20, artifact_store=store)

    frames = await _drain(executor, _LongResultNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body is None
    ref = completed.result.artifact
    assert ref is not None
    assert ref.size_bytes == 50
    path = store.path_for(ref.id)
    assert path is not None
    # The parcel is the COMPLETE result — nothing was cut.
    assert path.read_text(encoding="utf-8") == "X" * 50


@pytest.mark.asyncio
async def test_result_over_hard_cap_fails_loudly_with_both_byte_counts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    executor = Url4Executor(StaticIOLayer(), result_cap=10, hard_cap=30, artifact_store=store)

    with pytest.raises(ResolutionError) as excinfo:
        await _drain(executor, _LongResultNode())

    assert excinfo.value.code == "result_too_large"
    assert "50" in str(excinfo.value)  # actual bytes
    assert "30" in str(excinfo.value)  # allowed bytes
    # WHY: a refused result must not leave a parcel behind — nothing was deliverable.
    assert not any((tmp_path / "artifacts").glob("*")) or not (tmp_path / "artifacts").exists()


@pytest.mark.asyncio
async def test_over_cap_without_a_store_fails_instead_of_truncating() -> None:
    # WHY: an engine with no spill directory has no lossless path for a big result; the
    # only honest outcomes are inline or failure — never a cut body.
    executor = Url4Executor(StaticIOLayer(), result_cap=20, artifact_store=None)

    with pytest.raises(ResolutionError) as excinfo:
        await _drain(executor, _LongResultNode())

    assert excinfo.value.code == "result_too_large"


@pytest.mark.asyncio
async def test_deny_by_default_world_serves_no_routes_or_data() -> None:
    world = deny_by_default_world()
    with pytest.raises(ResolutionError):
        await world.fetch("https://anything", relative=False)


@pytest.mark.asyncio
async def test_unregistered_relurl_route_raises_resolution_error() -> None:
    io = StaticIOLayer()
    executor = Url4Executor(io)

    with pytest.raises(ResolutionError) as exc_info:
        async for _frame in executor.execute("/claude()!go"):
            pass

    assert exc_info.value.code == "resolution_failed"


@pytest.mark.asyncio
async def test_publish_run_orders_frames_per_spec_section_8() -> None:
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    stream = InMemoryEventStream()
    topic = "url4-executor-integration"

    await publish_run(stream, Url4Executor(io), topic, "https://a!go")

    frames = []

    async def _collect() -> None:
        async for frame in stream.subscribe(topic, from_sequence=1):
            frames.append(frame)
            if isinstance(frame, TerminatedEvent):
                return

    await asyncio.wait_for(_collect(), timeout=2.0)

    assert isinstance(frames[0], StartedEvent)
    assert isinstance(frames[-1], TerminatedEvent)
    assert frames[-1].data.status == "succeeded"

    tail_types = [type(f).__name__ for f in frames[-3:-1]]
    assert tail_types == ["CostUsageEvent", "ResultEvent"]
    subtree_frame = frames[-3]
    assert subtree_frame.data.scope == "subtree"

    for frame in frames[1:-3]:
        assert type(frame).__name__ in {"LogEvent", "SpanEvent", "CostUsageEvent"}
        if type(frame).__name__ == "CostUsageEvent":
            assert frame.data.scope == "self"


def _is_engine_module(module: str) -> bool:
    """True for the url4 ENGINE surface, false for the wire contract.

    `url4.streaming` ships in the same distribution as the engine but is the protocol vocabulary
    every Runner module is entitled to speak, so it is deliberately not an engine import. Bare
    `url4` IS: its package __init__ re-exports the engine's public API.
    """
    return module == "url4" or (
        module.startswith("url4.") and not module.startswith("url4.streaming")
    )


def _imports_url4_engine(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            _is_engine_module(alias.name) for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if _is_engine_module(node.module):
                return True
    return False


_ALLOWED_RUNNER_IMPORTERS = frozenset(
    {
        Path("screamingface_engine/runner/executor.py"),
        Path("screamingface_engine/runner/connector.py"),
        # OME-908: the fair-share io wrapper binds a run into the shared gate — an io-port
        # adapter in exactly connector's sense, so it shares the engine-import allowance.
        Path("screamingface_engine/runner/fair_share.py"),
    }
)


def _may_import_url4_engine(py_file: Path) -> bool:
    """Engine adapters and Engine-owned Benchmark extensions may speak URL4 directly."""

    relative = py_file.relative_to(_SRC_ROOT)
    return relative in _ALLOWED_RUNNER_IMPORTERS or relative.parts[:2] == (
        "screamingface_engine",
        "benchmarks",
    )


def test_only_engine_extensions_import_url4() -> None:
    """The URL4 ENGINE is confined to Runner adapters and Benchmark extensions.

    `url4.streaming` is exempt — it is the wire contract, which both halves speak. This scans
    the whole distribution. Benchmark definitions deliberately build structured URL4 and install
    routes on the shared Runner node; no other control-plane or shared module may import it.
    """
    offenders = [
        py_file
        for py_file in _SRC_ROOT.rglob("*.py")
        if _imports_url4_engine(py_file) and not _may_import_url4_engine(py_file)
    ]
    assert offenders == []

    allowed = {
        py_file.relative_to(_SRC_ROOT)
        for py_file in _SRC_ROOT.rglob("*.py")
        if py_file.relative_to(_SRC_ROOT) in _ALLOWED_RUNNER_IMPORTERS
        and _imports_url4_engine(py_file)
    }
    assert allowed == _ALLOWED_RUNNER_IMPORTERS


# --- per-span usage accumulation ---------------------------------------------------------

_SPAN = "0123456789abcdef"


def _usage(input_tokens: int, output_tokens: int) -> Usage:
    return Usage(
        span_id=_SPAN,
        provider="openrouter",
        model="m",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _one_node_two_usage_events() -> tuple[SpanData, CostUsageData, CostUsageData]:
    """Drive `_RunState` through ONE node that reports usage TWICE.

    This is the ordinary shape of a route whose mechanism resolves to `uses_web_tools`, not a
    corner case: every aigateway round trip in the tool loop reports its own usage against the
    same span.
    """
    state = _RunState()
    state.map(NodeStarted(span_id=_SPAN, parent_span_id=None, node_kind="RelUrlNode", detail="m"))
    state.map(_usage(124, 10))
    state.map(_usage(3558, 20))
    frames = state.map(NodeFinished(span_id=_SPAN, status="ok", engine_seq=1))
    span = next(f.payload for f in frames if isinstance(f.payload, SpanData))
    self_cost = next(
        f.payload
        for f in frames
        if isinstance(f.payload, CostUsageData) and f.payload.scope == "self"
    )
    return span, self_cost, state.build_subtree()


def test_a_span_accumulates_usage_across_every_report() -> None:
    # Regression: this used to ASSIGN, keeping only the final round trip.
    span, _, _ = _one_node_two_usage_events()

    assert (span.input_tokens, span.output_tokens) == (3682, 30)


def test_self_scope_cost_accumulates_usage_across_every_report() -> None:
    _, self_cost, _ = _one_node_two_usage_events()

    assert (self_cost.usage.input_tokens, self_cost.usage.output_tokens) == (3682, 30)


def test_self_and_subtree_agree_when_the_run_is_a_single_node() -> None:
    # The invariant the bug broke: per-node cost that under-reports against a run total that
    # does not is worse than either being wrong alone — they are reconciled against each other.
    _, self_cost, subtree = _one_node_two_usage_events()

    assert self_cost.usage.input_tokens == subtree.usage.input_tokens
    assert self_cost.usage.output_tokens == subtree.usage.output_tokens


@pytest.mark.asyncio
async def test_hard_cap_governs_even_when_knobs_are_inverted(tmp_path: Path) -> None:
    # WHY: inline_cap > hard_cap is an operator misconfiguration. If the inline check ran
    # first, a result under the (huge) inline cap would sail into one WS frame, bypassing
    # the hard cap and resurrecting the close-1009 websocket_disconnected failure the
    # client's frame bound was built to kill. The hard cap is absolute: it wins.
    store = ArtifactStore(tmp_path / "artifacts")
    executor = Url4Executor(StaticIOLayer(), result_cap=100, hard_cap=30, artifact_store=store)

    with pytest.raises(ResolutionError) as excinfo:
        await _drain(executor, _LongResultNode())  # 50 bytes: ≤ inline, > hard

    assert excinfo.value.code == "result_too_large"
    assert "30" in str(excinfo.value)


def test_the_bridge_records_its_high_water_mark() -> None:
    # FEATURE: bridge high-water reporting (OME-906). A run that overflowed told an operator
    # only THAT it overflowed; a run that came close told them nothing at all. The mark is
    # the difference between "this is fine" and "this is one cached Fusion from failing".
    bridge = _Bridge(maxsize=4)
    for i in range(3):
        bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))

    assert bridge.high_water == 3


@pytest.mark.asyncio
async def test_the_high_water_mark_is_a_mark_not_a_gauge() -> None:
    # INVARIANT: draining does NOT lower it. The peak is the diagnostic; a mark that fell
    # back with the queue would read as healthy on every run that recovered.
    bridge = _Bridge(maxsize=4)
    for i in range(3):
        bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))
    bridge.close()

    drained = [event async for event in bridge.drain()]

    assert len(drained) == 3
    assert bridge.high_water == 3


def test_a_backlog_within_the_soft_cap_is_not_reported_as_backlogged() -> None:
    bridge = _Bridge(maxsize=4)
    for i in range(4):
        bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))

    assert bridge.high_water == 4
    assert not bridge.backlogged


def test_a_backlog_past_the_soft_cap_is_reported_as_backlogged() -> None:
    bridge = _Bridge(maxsize=4)
    for i in range(6):
        bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))

    assert bridge.high_water == 6
    assert bridge.backlogged


def test_the_overflow_error_names_the_high_water_mark() -> None:
    # WHY the tiny budget: the hard cap is `budget // EVENT_SIZE_ESTIMATE_BYTES` (OME-906),
    # so a small budget keeps this unit's burst short instead of buffering the 131 072-event
    # default cap.
    bridge = _Bridge(maxsize=2, memory_budget=10_240)
    with pytest.raises(BridgeOverflowError) as excinfo:
        for i in range(bridge._hard_cap + 1):
            bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))

    # Asserts the PHRASE, not just the number: the hard cap is already in this message, and
    # at the moment of the raise the peak equals it — so a bare digit check passes on a
    # message that never learned to report the mark.
    assert f"peak {bridge.high_water}" in str(excinfo.value)


def _backlogged_bridge(*, events: int, maxsize: int = 4) -> _Bridge:
    """A bridge whose backlog is made of NON-Log events, which is the shape that matters.

    A Log-only burst pins the buffer AT the soft cap — `on_event` drops an incoming Log
    outright rather than appending it — so it never raises the mark and is already reported by
    the dropped-count line. Only lossless events climb toward the hard cap, which is the
    condition OME-906 exists to make visible.
    """
    bridge = _Bridge(maxsize=maxsize)
    for i in range(events):
        bridge.on_event(NodeStarted(f"span-{i}", None, "WebFetchNode", ""))
    return bridge


def test_a_backlogged_run_reports_its_high_water_mark_in_a_closing_log() -> None:
    bridge = _backlogged_bridge(events=9, maxsize=4)

    frames = _closing_logs(bridge, RunCacheCounters())

    marks = [
        f.payload
        for f in frames
        if isinstance(f.payload, LogData) and BRIDGE_HIGH_WATER in (f.payload.attributes or {})
    ]
    assert len(marks) == 1
    attributes = marks[0].attributes or {}
    assert attributes[BRIDGE_HIGH_WATER] == 9
    assert attributes[BRIDGE_SOFT_CAP] == 4
    # INVARIANT: a run-level statement, so it belongs to no span.
    assert all(f.span is None for f in frames)


def test_a_run_that_never_backlogged_reports_no_high_water_log() -> None:
    # WHY: `_closing_logs` stays silent when there is nothing to say — most expressions call
    # no gateway and never queue. An always-on line would make the signal worthless.
    bridge = _backlogged_bridge(events=3, maxsize=4)

    frames = _closing_logs(bridge, RunCacheCounters())

    assert frames == []


def test_a_backlog_exactly_at_the_soft_cap_is_not_yet_worth_reporting() -> None:
    # Boundary: `backlogged` is strictly GREATER than the soft cap. Reaching the cap is the
    # eviction policy working as designed, not a diagnosis.
    bridge = _backlogged_bridge(events=4, maxsize=4)

    assert bridge.high_water == 4
    assert _closing_logs(bridge, RunCacheCounters()) == []
