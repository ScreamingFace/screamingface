"""Installed benchmark roles emit activity without changing their execution contracts."""

import inspect
from collections.abc import Awaitable
from typing import cast

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.observations import RunObservations
from url4 import CodeCall, CodeInput
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_PRIVATE = "private malformed input"


def _code_call(path: str) -> CodeCall:
    """One call carrying every named source a Benchmark code mount reads (spec 2026-10-20 R1).

    WHY a well-formed Case beside private payloads: a code mount reads its sources by name, so
    each role reaches its own observed step and fails there on the private payload.
    """

    values = {
        "case": '{"id": 1, "case_id": "1"}',
        "attempt_1": _PRIVATE,
        "reasoning": _PRIVATE,
        "question": _PRIVATE,
        "trigger": _PRIVATE,
        "execution": _PRIVATE,
        "case_index": "0",
        "case_count": "1",
        "evaluations": _PRIVATE,
        "selected": "1",
    }
    inputs = tuple(
        CodeInput(position, name, value, 0.0)
        for position, (name, value) in enumerate(values.items(), start=1)
    )
    return CodeCall(path, {}, inputs)


async def _assert_code_roles(node, records, expected) -> None:
    """Every code mount (spec 2026-10-20 R1) emits its role's activity stage, privately."""

    for path, code in node._code.items():
        records.clear()
        try:
            result = code(_code_call(path))
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 — every role may refuse the private payload.
            pass
        if path.endswith("/commit-prompt"):
            # WHY: building the turn-2 prompt is not a stage of its own — it emits nothing.
            assert records == []
            continue
        assert [r["sf.activity.kind"] for r in records] == [expected[path.rsplit("/", 1)[1]]] * 2
        assert records[0]["sf.activity.state"] == "started"
        assert records[1]["sf.activity.state"] in {"completed", "failed"}
        assert "private" not in str(records)


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", BUILTIN_REGISTRATIONS, ids=lambda r: r.benchmark.id)
async def test_builtin_installers_declare_every_stage(monkeypatch, tmp_path, registration):
    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.phases.current_log_sink",
        lambda: lambda body, attrs, **kwargs: records.append(dict(attrs)),
    )
    node = Url4Node("stages")
    registration.benchmark.install(node, tmp_path)
    run = RunObservations((ActivityObserver,))
    expected = {
        "cases": "case_loading",
        "tasks": "grading",
        "check": "grading",
        "check-surface": "grading",
        "verdict": "grading",
        "criterion-evaluation": "grading",
        "rubric-evaluation": "grading",
        "case-evaluation": "grading",
        "case-result": "grading",
        "aggregate": "aggregation",
        "graded": "aggregation",
        "draco-pass.v1": "grading",
        "healthbench-pass.v1": "grading",
        "gdpval-pass.v1": "grading",
        "rubric-tasks": "grading",
        "criterion-verdict": "grading",
        "rubric-verdict": "grading",
    }
    with run.bind():
        for route in node._data.values():
            provider = route.provider
            assert callable(provider)
            records.clear()
            with pytest.raises(ResolutionError):
                provider()
            assert [r["sf.activity.kind"] for r in records] == ["case_loading"] * 2
        for route, handler in node._endpoints.items():
            records.clear()
            try:
                result = handler(Request(route, "private malformed input", "", {}))
                if inspect.isawaitable(result):
                    await result
            except ResolutionError:
                pass
            assert [r["sf.activity.kind"] for r in records] == [
                expected[route.rsplit("/", 1)[1]]
            ] * 2
            assert records[0]["sf.activity.state"] == "started"
            assert records[1]["sf.activity.state"] in {"completed", "failed"}
            assert "private" not in str(records)
        await _assert_code_roles(node, records, expected)
    await run.aclose()


@pytest.mark.asyncio
async def test_real_url4_candidate_stage_is_node_attached_and_output_unchanged():
    from screamingface_engine.world.candidate_adapter import install_candidate_invocation
    from url4.dag import run as execute
    from url4.observe import Log, NodeStarted

    node = Url4Node("candidate")
    install_candidate_invocation(node)

    @node.endpoint("/fake")
    async def answer(request):
        return "a private answer"

    from screamingface_engine.benchmarks.definition import inert_text
    from url4 import RelExpr, Text, expr, render, src

    recipe = "(model:0.0:/fake()!'Answer')!'$model'"
    expression = render(
        expr(
            src(
                # WHY: the Candidate contract (spec 2026-10-20 R2) — the Recipe is a source,
                # the model input the intent.
                RelExpr(
                    path="/benchmarks/candidate",
                    params=(("web_search", "false"),),
                    context=render(src(Text(inert_text(recipe)), name="recipe")),
                    intent=Text("question"),
                ),
                name="result",
                weight=0.0,
            ),
            intent=Text("$result"),
        )
    )
    events = []

    class Observer:
        def on_event(self, event):
            events.append(event)

    plain = await execute(expression, io=node)
    run = RunObservations((ActivityObserver,))
    with run.bind():
        observed = await execute(expression, io=node, observer=Observer())
    await run.aclose()
    assert observed == plain
    logs = [event for event in events if isinstance(event, Log)]
    assert [event.attributes["sf.activity.state"] for event in logs] == ["started", "completed"]
    assert all(event.attributes["sf.activity.kind"] == "answering" for event in logs)
    spans = {event.span_id for event in events if isinstance(event, NodeStarted)}
    assert all(event.span_id in spans for event in logs)
    assert "private answer" not in str(logs)


@pytest.mark.asyncio
async def test_imported_benchmark_stages_use_the_same_optional_port(monkeypatch, tmp_path):
    from screamingface_engine_inspect import single_shot

    monkeypatch.setattr(single_shot, "_BENCHMARKS_BY_ID", {})
    # WHY: installation is lazy; this test needs no optional scorer packages or paid calls.
    monkeypatch.setattr(single_shot, "pinned_inspect_packages", lambda: ("test",))
    benchmark = single_shot.single_shot_benchmark(
        benchmark_key="stage-probe",
        title="Stage probe",
        description="Test stages",
        focus="Tests",
        dataset_url="https://example.com/data",
        case_count=1,
        revision_pins=("test",),
        scorer_factory=lambda: None,
        prepare=lambda out: {},
        install=lambda node, root: None,
        with_check_surface=True,
        difficulty="easy",
        failure_policy="coverage_declare",
    )
    node = Url4Node("imported")
    single_shot.install_imported_benchmark(node, tmp_path, benchmark.benchmark.id)
    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.phases.current_log_sink",
        lambda: lambda body, attrs, **kwargs: records.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    with run.bind():
        records.clear()
        with pytest.raises(ResolutionError):
            result = node._endpoints[benchmark.check_surface_route](
                Request(benchmark.check_surface_route, "", "", {})
            )
            if inspect.isawaitable(result):
                await result
        assert [r["sf.activity.kind"] for r in records] == ["grading", "grading"]
        # WHY: the check runs in process inside the case-evaluation code (spec 2026-10-20 R1);
        # its answering stage is still the only stage that Case record emits.
        records.clear()
        # A private non-record attempt fails the Case after its check stage ran and failed.
        with pytest.raises(ValueError):
            node._code[benchmark.case_evaluation_route](_code_call(benchmark.case_evaluation_route))
        assert [r["sf.activity.kind"] for r in records] == ["answering", "answering"]
        records.clear()
        with pytest.raises(ResolutionError):
            await cast(
                Awaitable[str],
                node._code[benchmark.aggregate_route](_code_call(benchmark.aggregate_route)),
            )
        assert [r["sf.activity.kind"] for r in records] == ["aggregation", "aggregation"]
    await run.aclose()
