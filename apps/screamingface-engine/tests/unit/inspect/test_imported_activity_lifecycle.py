"""Observe the complete imported judged recipe, not isolated scorer callbacks."""

import json

import httpx
import pytest

pytest.importorskip("inspect_ai")

from test_judge_observability import _assembled, _judged_spec  # noqa: E402

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from screamingface_engine.world.candidate_adapter import install_candidate_invocation  # noqa: E402
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)
from url4 import RelExpr, Text, build, expr, render, src, text  # noqa: E402
from url4.dag import run as execute  # noqa: E402
from url4.observe import Log  # noqa: E402


def _board(monkeypatch, tmp_path):
    board = _assembled(_judged_spec(), monkeypatch)
    root = tmp_path / board.benchmark.id
    (root / "targets").mkdir(parents=True)
    (root / "cases.json").write_text(
        json.dumps(
            [
                {"id": 1, "input": "Capital of France?"},
                {"id": 2, "input": "Capital of Italy?"},
            ]
        )
    )
    for case_id, answer in ((1, "Paris"), (2, "Rome")):
        (root / "targets" / f"{case_id}.json").write_text(json.dumps({"target": answer}))
    return board


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_candidate,failed_judge", [(False, False), (True, False), (False, True)]
)
async def test_imported_judged_recipe_records_then_grades_cases(
    monkeypatch, tmp_path, failed_candidate, failed_judge
):
    board = _board(monkeypatch, tmp_path)
    client = httpx.AsyncClient(
        base_url="http://gateway",
        transport=httpx.MockTransport(_gateway(failed_candidate, failed_judge)),
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            base_url="http://gateway",
            default_model="writer",
            models=(ModelSpec(id="writer"), ModelSpec(id="judge-4")),
            allow_outbound=False,
        ),
        client=client,
    )
    node = world.node
    install_candidate_invocation(node)
    board.benchmark.install(node, tmp_path)
    events = []

    class Collector:
        def on_event(self, event):
            if isinstance(event, Log) and "sf.activity.kind" in event.attributes:
                events.append(dict(event.attributes))

    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            result = json.loads(
                await execute(
                    render(
                        expr(
                            src(
                                text(
                                    render(
                                        RelExpr(
                                            path="/writer", context="$input", intent=Text("answer")
                                        )
                                    )
                                ),
                                name="candidate",
                                weight=0.0,
                            ),
                            build(str(board.benchmark.resource(limit=2)["url4"])),
                            intent=text(""),
                        )
                    ),
                    io=node,
                    observer=Collector(),
                )
            )
    finally:
        await run.aclose()
        await world.aclose()
        await client.aclose()
    assert result["score"] == 1.0, json.dumps(result)
    _assert_lifecycle(events, failed_candidate, failed_judge)


def _gateway(failed_candidate, failed_judge):
    def respond(request):
        payload = json.loads(request.content)
        judge = payload["model"] == "judge-4"
        failed = failed_candidate and not judge and "Italy" in json.dumps(payload["messages"])
        if failed or (failed_judge and judge and "Rome" in json.dumps(payload["messages"])):
            return httpx.Response(
                400, json={"detail": {"code": "bad_request", "message": "Fake rejection"}}
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "Correct.\n\nGRADE: C" if judge else "Paris"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    return respond


def _assert_lifecycle(events, failed_candidate, failed_judge):
    completed = [e for e in events if e["sf.activity.state"] == "completed"]
    # INVARIANT: packaging/recording is not grading; only scorer verdicts earn Graded.
    grading = [e for e in completed if e["sf.activity.kind"] == "grading"]
    assert [(e.get("sf.activity.case_id"), e.get("sf.activity.scope")) for e in grading] == [
        (case_id, "case") for case_id in ([1] if failed_candidate or failed_judge else [1, 2])
    ]
    judges = [e for e in completed if e.get("sf.activity.model_id") == "judge-4"]
    assert [e.get("sf.activity.case_id") for e in judges] == (
        [1] if failed_candidate or failed_judge else [1, 2]
    )
    assert all(e.get("sf.activity.role") == "judge" for e in judges)
    recording = [e for e in completed if e.get("sf.activity.action") == "recording"]
    assert [e.get("sf.activity.case_id") for e in recording] == (
        [1] if failed_candidate else [1, 2]
    )
    assert max(events.index(e) for e in recording) < min(events.index(e) for e in judges)
    assert completed[-1]["sf.activity.kind"] == "aggregation"
    assert all(
        "sf.activity.case_id" in e
        for e in events
        if e["sf.activity.kind"] not in {"case_loading", "aggregation"}
    )
    for verdict in grading:
        judge = next(
            e for e in judges if e["sf.activity.case_id"] == verdict["sf.activity.case_id"]
        )
        assert events.index(judge) < events.index(verdict)

    if failed_judge:
        failures = [
            e
            for e in events
            if e["sf.activity.kind"] == "grading" and e["sf.activity.state"] == "failed"
        ]
        assert [e["sf.activity.case_id"] for e in failures] == [2]
