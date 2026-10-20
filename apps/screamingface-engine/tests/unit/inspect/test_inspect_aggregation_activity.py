"""Real imported aggregation preserves observation context on its owning event loop."""

import json

import pytest

pytest.importorskip("inspect_ai.scorer")

from test_inspect_gsm8k_benchmark import GSM8K_BENCHMARK, _node, _row  # noqa: E402

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.benchmarks.definition import inert_text  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from screamingface_engine_inspect.single_shot import benchmark_aggregate  # noqa: E402
from url4 import RelUrl, expr, render, src, text  # noqa: E402
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
    # WHY the run-terminal shape: `aggregate` is code over the named `evaluations` and
    # `selected` sources (spec 2026-10-20 R1), not an endpoint read by an intent string.
    expression = render(
        expr(
            src(text(inert_text(rows)), name="evaluations", weight=0.0),
            src(text("2"), name="selected", weight=0.0),
            intent=RelUrl(GSM8K_BENCHMARK.aggregate_route),
        )
    )
    run = RunObservations((lambda: ActivityObserver(enabled=enabled),))
    try:
        with run.bind():
            result = json.loads(await execute(expression, io=node, observer=Collector()))
    finally:
        await run.aclose()
        await node.aclose()
    assert result == benchmark_aggregate(
        GSM8K_BENCHMARK, rows, tmp_path / GSM8K_BENCHMARK.benchmark.id, case_ids=(1, 2)
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
