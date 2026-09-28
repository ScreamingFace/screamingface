"""Installed benchmark roles emit activity without changing their execution contracts."""

import inspect

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.observations import RunObservations
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", BUILTIN_REGISTRATIONS, ids=lambda r: r.benchmark.id)
async def test_builtin_installers_declare_every_stage(monkeypatch, tmp_path, registration):
    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.stages.current_log_sink",
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
        "aggregate": "aggregation",
        "draco-pass.v1": "grading",
        "healthbench-pass.v1": "grading",
        "gdpval-pass.v1": "grading",
        "rubric-tasks": "grading",
        "criterion-verdict": "grading",
        "rubric-verdict": "grading",
    }
    with run.bind():
        for provider in node._data.values():
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

    from url4 import RelExpr, Text, expr, render, src

    recipe = "(model:0.0:/fake()!'Answer')!'$model'"
    expression = render(
        expr(
            src(
                RelExpr(
                    path="/benchmarks/candidate",
                    params=(("web_search", "false"),),
                    context=None,
                    intent=Text(recipe),
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
async def test_imported_board_stages_use_the_same_optional_port(monkeypatch, tmp_path):
    from screamingface_engine_inspect import single_shot

    monkeypatch.setattr(single_shot, "_BOARDS_BY_ID", {})
    # WHY: installation is lazy; this test needs no optional scorer packages or paid calls.
    monkeypatch.setattr(single_shot, "pinned_inspect_packages", lambda: ("test",))
    board = single_shot.single_shot_board(
        board_key="stage-probe",
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
    )
    node = Url4Node("imported")
    single_shot.install_imported_board(node, tmp_path, board.benchmark.id)
    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.stages.current_log_sink",
        lambda: lambda body, attrs, **kwargs: records.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    with run.bind():
        for route, kind in (
            (board.check_route, "answering"),
            (board.check_surface_route, "grading"),
            (board.case_evaluation_route, None),
            (board.aggregate_route, "aggregation"),
        ):
            records.clear()
            with pytest.raises(ResolutionError):
                result = node._endpoints[route](Request(route, "", "", {}))
                if inspect.isawaitable(result):
                    await result
            assert [r["sf.activity.kind"] for r in records] == (
                [] if kind is None else [kind, kind]
            )
    await run.aclose()
