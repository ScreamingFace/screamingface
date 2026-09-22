"""Final candidate rows must not wait behind slower siblings."""

import asyncio
from threading import Event
from typing import Any, cast

from test_live_candidate_progress import candidate, outcome, report_for

from screamingface._evaluation.runner import _run_candidates_async, _run_candidates_sync
from screamingface._ui.evaluation_state import _EvaluationProgress


def test_sync_completion_arrives_before_slow_first_candidate():
    slow, fast = candidate("slow"), candidate("fast")
    ready = Event()
    seen = []

    class Transport:
        def run(self, selected, observer):
            if selected == slow:
                assert ready.wait(2)
            return outcome(selected.name)

    def completed(selected, result):
        seen.append(selected.name)
        if selected == fast:
            ready.set()

    results = _run_candidates_sync(cast(Any, Transport()), (slow, fast), None, completed)
    assert seen == ["fast", "slow"]
    assert [c.name for c, _ in results] == ["slow", "fast"]


def test_async_completion_arrives_before_slow_first_candidate():
    async def run():
        slow, fast = candidate("slow"), candidate("fast")
        ready = asyncio.Event()
        seen = []

        class Transport:
            async def run(self, selected, observer):
                if selected == slow:
                    await asyncio.wait_for(ready.wait(), 2)
                return outcome(selected.name)

        def completed(selected, result):
            seen.append(selected.name)
            if selected == fast:
                ready.set()

        results = await _run_candidates_async(cast(Any, Transport()), (slow, fast), None, completed)
        assert seen == ["fast", "slow"]
        assert [c.name for c, _ in results] == ["slow", "fast"]

    asyncio.run(run())


def test_candidate_result_reconciles_only_its_row():
    slow, fast = candidate("slow"), candidate("fast")
    progress = _EvaluationProgress(candidates=(slow, fast), case_count=1)
    progress.candidate_result(report_for(fast).candidates[0])
    assert progress.rows[1].score == 0.75
    assert progress.rows[1].cost_usd == report_for(fast).candidates[0].usage.cost_usd
    assert progress.rows[1].completed_cases == 1
    assert progress.rows[1].duration_seconds == 2
    assert progress.rows[0].result is None
    assert not progress.complete


def test_validated_result_reaches_widget_before_other_candidate(monkeypatch):
    import json
    import sys
    from dataclasses import replace

    from test_benchmark_compilation import _Transport
    from test_evaluation_compilation import evaluation_plan
    from test_live_candidate_progress import _fake_widgets, _widget_text

    from screamingface._evaluation.completion import completion_callback
    from screamingface._evaluation.runner import _SyncEventObserver
    from screamingface._ui.evaluation_widget import _NotebookEvaluationView

    monkeypatch.setitem(sys.modules, "ipywidgets", _fake_widgets())
    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    slow, fast = candidate("slow"), candidate("fast")
    view = _NotebookEvaluationView((slow, fast), 1, "draco", tick=False)
    value = _Transport().run(fast, None)
    assert value.result_body is not None
    payload = json.loads(value.result_body)
    payload["benchmark_id"] = "draco"
    value = replace(value, result_body=json.dumps(payload))
    callback = completion_callback(evaluation_plan((slow, fast)), _SyncEventObserver(view, None))
    assert callback is not None
    callback(fast, value)
    assert view._progress.rows[1].score == 0.8
    assert "0.8" in _widget_text(view._activity_rows[1].widget)
    assert view._progress.rows[0].result is None
    assert not view._done.is_set()
    view.close()


def test_single_candidate_completion_failure_does_not_change_outcome():
    selected = candidate("one")
    result = outcome(selected.name)

    class Transport:
        def run(self, candidate, observer):
            return result

    def broken(candidate, outcome):
        raise RuntimeError("display failed")

    assert _run_candidates_sync(cast(Any, Transport()), (selected,), None, broken) == (
        (selected, result),
    )


def test_async_single_candidate_notifies_result():
    selected = candidate("one")
    result = outcome(selected.name)
    received = []

    class Transport:
        async def run(self, candidate, observer):
            return result

    asyncio.run(
        _run_candidates_async(
            cast(Any, Transport()),
            (selected,),
            None,
            lambda candidate, value: received.append((candidate, value)),
        )
    )
    assert received == [(selected, result)]
