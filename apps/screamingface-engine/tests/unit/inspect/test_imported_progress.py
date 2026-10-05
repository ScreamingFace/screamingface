"""The real imported aggregation route emits native scores over the Log transport."""

import json

import pytest

pytest.importorskip("inspect_ai.scorer")

from test_inspect_gsm8k_benchmark import GSM8K_BENCHMARK, _node, _row  # noqa: E402

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.dag import run as execute  # noqa: E402
from url4.observe import Log  # noqa: E402


@pytest.mark.asyncio
async def test_imported_aggregate_publishes_prefix_score_and_preserves_final(tmp_path):
    node = _node(tmp_path)
    snapshots = []

    class Collector:
        def on_event(self, event):
            if isinstance(event, Log) and event.attributes.get("sf.progress.schema"):
                snapshots.append(dict(event.attributes))

    expression = render(
        expr(
            src(
                text(json.dumps([_row(1, "ANSWER: 42"), _row(2, "ANSWER: 59")])),
                name="payload",
                weight=0.0,
            ),
            RelExpr(
                path=GSM8K_BENCHMARK.aggregate_route, context="$payload", intent=Text("aggregate:2")
            ),
            intent=Text(""),
        )
    )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            result = json.loads(await execute(expression, io=node, observer=Collector()))
    finally:
        await run.aclose()
        await node.aclose()
    assert snapshots[0]["sf.progress.graded"] == 1
    assert snapshots[0]["sf.progress.score"] == 1.0
    assert result["score"] == 0.5
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0]
