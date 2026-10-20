"""The real imported aggregation route emits native scores over the Log transport."""

import json

import pytest

pytest.importorskip("inspect_ai.scorer")

from test_inspect_gsm8k_benchmark import GSM8K_BENCHMARK, _node, _row  # noqa: E402

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from url4 import (  # noqa: E402
    RelUrl,
    expr,
    literal,  # noqa: E402
    render,
    src,
    text,
)
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

    # WHY the run-terminal shape: `aggregate` is code over the named `evaluations` and
    # `selected` sources (spec 2026-10-20 R1), not an endpoint read by an intent string.
    expression = render(
        expr(
            src(
                literal(json.dumps([_row(1, "ANSWER: 42"), _row(2, "ANSWER: 59")])),
                name="evaluations",
                weight=0.0,
            ),
            src(text("2"), name="selected", weight=0.0),
            intent=RelUrl(GSM8K_BENCHMARK.aggregate_route),
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
