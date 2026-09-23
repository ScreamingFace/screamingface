"""Real imported aggregation preserves observation context on its owning event loop."""

import json

import pytest

pytest.importorskip("inspect_ai.scorer")

from test_inspect_gsm8k_board import GSM8K_BOARD, _node, _row  # noqa: E402

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from screamingface_engine_inspect.single_shot import board_aggregate  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.dag import run as execute  # noqa: E402
from url4.observe import Log  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_imported_aggregate_emits_case_grading_with_original_score(tmp_path, enabled):
    node = _node(tmp_path)
    events = []

    class Collector:
        def on_event(self, event):
            events.append(event)

    rows = json.dumps([_row(1, "ANSWER: 42"), _row(2, "ANSWER: 59")])
    expression = render(
        expr(
            src(text(rows), name="payload", weight=0.0),
            RelExpr(
                path=GSM8K_BOARD.aggregate_route,
                context="$payload",
                intent=Text("aggregate:2"),
            ),
            intent=Text(""),
        )
    )
    run = RunObservations((lambda: ActivityObserver(enabled=enabled),))
    try:
        with run.bind():
            result = json.loads(await execute(expression, io=node, observer=Collector()))
    finally:
        await run.aclose()
        await node.aclose()
    assert result == board_aggregate(
        GSM8K_BOARD, rows, tmp_path / GSM8K_BOARD.benchmark.id, case_ids=(1, 2)
    )
    assert result["score"] == 0.5
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0]
    facts = [event.attributes for event in events if isinstance(event, Log)]
    case_facts = [fact for fact in facts if fact.get("sf.activity.scope") == "case"]
    if not enabled:
        assert not facts
    else:
        assert [
            (fact["sf.activity.case_id"], fact["sf.activity.state"]) for fact in case_facts
        ] == [(1, "started"), (1, "completed"), (2, "started"), (2, "completed")]
