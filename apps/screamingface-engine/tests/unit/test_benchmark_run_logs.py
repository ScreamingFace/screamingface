"""Dormant Benchmark adapter for the generic run Log seam (OME-934)."""

from __future__ import annotations

import ast
import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks import Benchmark, BenchmarkRegistry
from screamingface_engine.benchmarks.run_logs import (
    BenchmarkRunLogAdapter,
    emit_benchmark_run_log,
)
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner.run_logs import LogScalar, StructuredLogEmitter
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig
from url4 import RelExpr, render, text
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import LogData, LogEvent, TerminatedEvent

_SRC = Path(__file__).resolve().parents[2] / "src/screamingface_engine"


def _benchmark(benchmark_id: str) -> Benchmark:
    return Benchmark(
        id=benchmark_id,
        title=f"{benchmark_id} benchmark",
        description="A structural run-Log adapter probe.",
        revision="probe-v1",
        case_count=1,
        build=lambda _selected: text("unused"),
    )


def _capture() -> tuple[
    list[tuple[str, dict[str, LogScalar]]],
    StructuredLogEmitter,
]:
    records: list[tuple[str, dict[str, LogScalar]]] = []

    def emit(body: str, attributes: Mapping[str, LogScalar]) -> None:
        records.append((body, dict(attributes)))

    return records, emit


def test_registered_benchmark_claim_activates_an_otherwise_inert_scope() -> None:
    registry = BenchmarkRegistry((_benchmark("alpha"),))
    adapter = BenchmarkRunLogAdapter(registry)
    records, emit = _capture()
    scope = adapter.open_run_scope("(((deliberately-not-parsed", emit)
    assert scope is not None

    with scope:
        emit_benchmark_run_log("alpha", "benchmark observation", {"observed": 1})

    assert records == [("benchmark observation", {"observed": 1})]


def test_zero_claims_and_unknown_claim_are_silent_on_the_run_stream(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = BenchmarkRegistry((_benchmark("alpha"),))
    adapter = BenchmarkRunLogAdapter(registry)
    records, emit = _capture()
    caplog.set_level(logging.WARNING)
    scope = adapter.open_run_scope("opaque", emit)
    assert scope is not None

    with scope:
        emit_benchmark_run_log("unknown", "must not publish", {"observed": 1})

    assert records == []
    assert "unknown Benchmark run Log claim ignored" in caplog.text
    assert "must not publish" not in caplog.text


def test_conflicting_benchmark_owner_disables_the_recorder_without_choosing_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = BenchmarkRegistry((_benchmark("alpha"), _benchmark("beta")))
    adapter = BenchmarkRunLogAdapter(registry)
    records, emit = _capture()
    caplog.set_level(logging.WARNING)
    scope = adapter.open_run_scope("opaque", emit)
    assert scope is not None

    with scope:
        emit_benchmark_run_log("alpha", "first", {"observed": 1})
        emit_benchmark_run_log("beta", "conflict", {"observed": 2})
        emit_benchmark_run_log("alpha", "disabled", {"observed": 3})

    assert records == [("first", {"observed": 1})]
    assert "conflicting Benchmark run Log claims; instrumentation disabled" in caplog.text
    assert "alpha" not in caplog.text
    assert "beta" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_scopes_are_task_local() -> None:
    registry = BenchmarkRegistry((_benchmark("alpha"), _benchmark("beta")))
    adapter = BenchmarkRunLogAdapter(registry)
    both_started = asyncio.Event()
    started = 0

    async def run(benchmark_id: str) -> list[tuple[str, dict[str, LogScalar]]]:
        nonlocal started
        records, emit = _capture()
        scope = adapter.open_run_scope("same opaque URL4", emit)
        assert scope is not None
        with scope:
            started += 1
            if started == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            emit_benchmark_run_log(
                benchmark_id,
                f"{benchmark_id} observation",
                {"owner": benchmark_id},
            )
        return records

    alpha, beta = await asyncio.gather(run("alpha"), run("beta"))

    assert alpha == [("alpha observation", {"owner": "alpha"})]
    assert beta == [("beta observation", {"owner": "beta"})]


def test_nested_scope_restores_the_outer_recorder() -> None:
    registry = BenchmarkRegistry((_benchmark("alpha"), _benchmark("beta")))
    adapter = BenchmarkRunLogAdapter(registry)
    outer, emit_outer = _capture()
    inner, emit_inner = _capture()
    outer_scope = adapter.open_run_scope("outer", emit_outer)
    inner_scope = adapter.open_run_scope("inner", emit_inner)
    assert outer_scope is not None and inner_scope is not None

    with outer_scope:
        emit_benchmark_run_log("alpha", "outer before", {"step": 1})
        with inner_scope:
            emit_benchmark_run_log("beta", "inner", {"step": 2})
        emit_benchmark_run_log("alpha", "outer after", {"step": 3})

    assert outer == [("outer before", {"step": 1}), ("outer after", {"step": 3})]
    assert inner == [("inner", {"step": 2})]


@pytest.mark.asyncio
async def test_child_task_retaining_closed_recorder_cannot_publish_late(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = BenchmarkRegistry((_benchmark("alpha"),))
    adapter = BenchmarkRunLogAdapter(registry)
    records, emit = _capture()
    release = asyncio.Event()
    caplog.set_level(logging.WARNING)

    async def late() -> None:
        await release.wait()
        emit_benchmark_run_log("alpha", "late private body", {"late": True})

    scope = adapter.open_run_scope("opaque", emit)
    assert scope is not None
    with scope:
        task = asyncio.create_task(late())
    release.set()
    await task

    assert records == []
    assert "closed Benchmark run Log recorder ignored" in caplog.text
    assert "late private body" not in caplog.text


def _progress_benchmark() -> Benchmark:
    benchmark_id = "progress-probe"
    route = "/benchmarks/progress-probe/run"

    def install(node: Url4Node, _root: Path) -> None:
        async def run(_request: Request) -> str:
            emit_benchmark_run_log(
                benchmark_id,
                "benchmark probe",
                {"probe.completed": 1},
            )
            return "probe result"

        node.endpoint(route)(run)

    return Benchmark(
        id=benchmark_id,
        title="Progress Probe",
        description="A production-composition progress transport probe.",
        revision="progress-probe-v1",
        case_count=1,
        build=lambda _selected: RelExpr(path=route, context="case", intent=text("run")),
        install=install,
    )


def _world_config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model="provider/model",
            models=(ModelSpec(id="provider/model"),),
        )
    )


@pytest.mark.asyncio
async def test_production_composition_delivers_benchmark_record_on_sequenced_log_stream(
    tmp_path: Path,
) -> None:
    benchmark = _progress_benchmark()
    registry = BenchmarkRegistry((benchmark,))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        base_url="http://aigateway.test",
    )
    executor = build_executor(
        {},
        _world_config(),
        client=client,
        benchmarks=registry,
        benchmark_assets_root=tmp_path,
    )
    stream = InMemoryEventStream()
    topic = "ome-934-composition"

    try:
        await publish_run(stream, executor, topic, render(benchmark.protocol(1)))
    finally:
        await client.aclose()

    frames = []
    async for frame in stream.subscribe(topic, from_sequence=1):
        frames.append(frame)
        if isinstance(frame, TerminatedEvent):
            break
    logs = [
        frame
        for frame in frames
        if isinstance(frame, LogEvent) and frame.data.body == "benchmark probe"
    ]
    assert len(logs) == 1
    assert logs[0].data.attributes == {"probe.completed": 1}
    sequences = [int(frame.sequence) for frame in frames if frame.sequence is not None]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


@pytest.mark.asyncio
async def test_production_composition_with_empty_registry_emits_no_new_log() -> None:
    executor = build_executor({}, WorldConfig())

    frames = [frame async for frame in executor.execute(render(text("unchanged")))]

    assert not any(
        isinstance(frame, Traced) and isinstance(frame.payload, LogData) for frame in frames
    )
    assert isinstance(frames[-1], Completed)
    assert frames[-1].result.body == "unchanged"


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_only_composition_root_imports_concrete_benchmark_run_log_adapter() -> None:
    adapter_module = "screamingface_engine.benchmarks.run_logs"
    runner = _SRC / "runner"

    offenders = [
        path.relative_to(_SRC)
        for path in runner.glob("*.py")
        if path.name != "main.py" and adapter_module in _imported_modules(path)
    ]

    assert offenders == []


def _recursive_concrete_adapter_importers(runner: Path) -> list[Path]:
    adapter_module = "screamingface_engine.benchmarks.run_logs"
    composition_root = runner / "main.py"
    return [
        path
        for path in runner.rglob("*.py")
        if path != composition_root and adapter_module in _imported_modules(path)
    ]


def test_recursive_layering_guard_exempts_only_the_root_composition_module(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "runner"
    nested = runner / "nested"
    nested.mkdir(parents=True)
    import_line = "import screamingface_engine.benchmarks.run_logs\n"
    (runner / "main.py").write_text(import_line, encoding="utf-8")
    nested_main = nested / "main.py"
    nested_main.write_text(import_line, encoding="utf-8")

    assert _recursive_concrete_adapter_importers(runner) == [nested_main]


def test_runner_tree_imports_concrete_benchmark_adapter_only_at_composition_root() -> None:
    runner = _SRC / "runner"

    offenders = [path.relative_to(_SRC) for path in _recursive_concrete_adapter_importers(runner)]

    assert offenders == []


def test_generic_runner_tree_never_imports_benchmark_progress_semantics() -> None:
    semantic_module = "screamingface_engine.benchmarks.progress"
    runner = _SRC / "runner"

    offenders = [
        path.relative_to(_SRC)
        for path in runner.rglob("*.py")
        if semantic_module in _imported_modules(path)
    ]

    assert offenders == []
