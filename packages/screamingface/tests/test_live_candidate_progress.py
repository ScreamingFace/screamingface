from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate, _compiled_candidate, _compiled_operation
from screamingface._evaluation.runner import (
    _abort_event_observer,
    _AsyncEventObserver,
    _reconcile_event_observer,
    _run_candidates_async,
    _run_candidates_sync,
    _SyncEventObserver,
)
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import evaluation_panel_html

_START = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def candidate(name: str) -> Candidate:
    operation = _compiled_operation(
        id=f"op_{name}",
        kind="model",
        label=f"{name} answer",
        depends_on=(),
    )
    return _compiled_candidate(
        name=name,
        kind="model",
        models=(f"provider/{name}",),
        url4=f"(@)!'{name}'",
        operations=(operation,),
    )


def span(
    sequence: int,
    *,
    run_id: str,
    operation: str = "RelUrlNode",
    name: str = "/benchmarks/case-execution",
    status: str = "ok",
    request_model: str | None = None,
    cache_status: str | None = None,
) -> sf.events.Span:
    return sf.events.Span(
        id=f"{run_id}_{sequence}",
        run_id=run_id,
        sequence=sequence,
        timestamp=_START + timedelta(seconds=sequence),
        source=f"/trace/{run_id}/node/{sequence}",
        name=name,
        operation=operation,
        start=_START,
        end=_START + timedelta(seconds=1),
        status=cast(Any, status),
        request_model=request_model,
        cache_status=cast(Any, cache_status),
    )


def test_candidate_rows_exist_in_input_order_before_events() -> None:
    candidates = tuple(candidate(f"candidate-{index}") for index in range(10))

    progress = _EvaluationProgress(candidates=candidates, case_count=100)

    assert [row.candidate.name for row in progress.rows] == [
        candidate.name for candidate in candidates
    ]
    assert [(row.status, row.completed_cases, row.total_cases) for row in progress.rows] == [
        ("queued", 0, 100)
    ] * 10


def test_interleaved_terminal_case_spans_advance_only_the_bound_candidate() -> None:
    opus = candidate("opus")
    gpt = candidate("gpt")
    progress = _EvaluationProgress(candidates=(opus, gpt), case_count=100)

    progress.observe(opus, span(1, run_id="run_opus"))
    progress.observe(gpt, span(1, run_id="run_gpt"))
    progress.observe(opus, span(2, run_id="run_opus", status="error"))

    assert progress.rows[0].completed_cases == 2
    assert progress.rows[0].failed_cases == 1
    assert progress.rows[1].completed_cases == 1


def test_only_the_local_case_execution_span_advances_case_progress() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=3)

    progress.observe(
        opus,
        span(
            1,
            run_id="run_opus",
            operation="RemoteFetchNode",
        ),
    )
    progress.observe(
        opus,
        span(
            2,
            run_id="run_opus",
            operation="chat",
            name="chat",
            request_model="provider/opus",
        ),
    )
    progress.observe(
        opus,
        span(
            3,
            run_id="run_opus",
            name="/benchmarks/aggregate",
        ),
    )

    assert progress.rows[0].completed_cases == 0

    progress.observe(opus, span(4, run_id="run_opus"))

    assert progress.rows[0].completed_cases == 1


def test_sync_observer_binds_candidate_without_changing_public_callback() -> None:
    opus = candidate("opus")
    event = span(1, run_id="run_opus")
    observed: list[tuple[Candidate, sf.Event]] = []
    public: list[sf.Event] = []

    class Builtin:
        def observe(self, selected: Candidate, accepted: sf.Event) -> None:
            observed.append((selected, accepted))

    observer = _SyncEventObserver(cast(Any, Builtin()), public.append)

    observer.bind(opus)(event)

    assert observed == [(opus, event)]
    assert public == [event]


def test_one_thousand_terminal_spans_reach_exact_independent_totals() -> None:
    candidates = tuple(candidate(f"candidate-{index}") for index in range(10))
    progress = _EvaluationProgress(candidates=candidates, case_count=100)

    for case_number in range(1, 101):
        for index, selected in enumerate(candidates):
            progress.observe(
                selected,
                span(case_number, run_id=f"run_{index}"),
            )

    assert [row.completed_cases for row in progress.rows] == [100] * 10


def test_candidate_cost_and_cache_evidence_remain_scoped_to_its_row() -> None:
    opus = candidate("opus")
    gpt = candidate("gpt")
    progress = _EvaluationProgress(candidates=(opus, gpt), case_count=1)

    progress.observe(
        opus,
        sf.events.Usage(
            id="usage_opus",
            run_id="run_opus",
            sequence=1,
            timestamp=_START,
            source="/trace/run_opus/node/root",
            scope="self",
            provider="provider",
            model="opus",
            pricing_version="v1",
            usage=sf.Usage(cost_usd=Decimal("0.25")),
        ),
    )
    progress.observe(
        gpt,
        span(
            1,
            run_id="run_gpt",
            operation="chat",
            name="chat",
            request_model="provider/gpt",
        ),
    )
    progress.observe(
        gpt,
        span(
            2,
            run_id="run_gpt",
            operation="chat",
            name="chat",
            request_model="provider/gpt",
            cache_status="hit",
        ),
    )

    assert progress.rows[0].cost_usd == Decimal("0.25")
    assert progress.rows[1].cost_usd is None
    assert progress.rows[0].cache_hit_rate is None
    assert progress.rows[1].cache_hit_rate == 1.0


def outcome(name: str) -> _RunOutcome:
    return _RunOutcome(
        run_id=f"run_{name}",
        started_at=_START,
        completed_at=_START + timedelta(seconds=1),
        result_body="{}",
        media_type="application/json",
        root_usage=None,
    )


def report_for(selected: Candidate, *, score: float | None = 0.75) -> sf.Report:
    grade = sf.CaseGrade(method="fixture", score=score, metrics={}, checks=())
    case = sf.CaseResult(
        case_id=1,
        input="Question",
        output="Answer",
        finish_reason="stop",
        grade=grade,
        failures=(),
        metadata={},
    )
    benchmark = sf.BenchmarkInfo(id="draco", revision="fixture", case_count=100)
    result = sf.CandidateResult(
        benchmark=benchmark,
        run_id=f"run_{selected.name}",
        started_at=_START,
        completed_at=_START + timedelta(seconds=2),
        name=selected.name,
        kind=selected.kind,
        url4=selected.url4,
        models=selected.models,
        operations=selected.operations,
        score=score,
        coverage=1.0 if score is not None else 0.0,
        metrics={},
        cases=(case,),
        members=(),
        failures=(),
        usage=sf.Usage(
            input_tokens=1_000,
            output_tokens=200,
            cost_usd=Decimal("0.40"),
        ),
    )
    return sf.Report(benchmark=benchmark, case_count=1, candidates=(result,))


def test_sync_candidate_runner_uses_one_bound_observer_per_run() -> None:
    candidates = (candidate("opus"), candidate("gpt"))
    observed: list[tuple[str, str]] = []

    class Builtin:
        def observe(self, selected: Candidate, event: sf.Event) -> None:
            observed.append((selected.name, event.run_id))

    class Transport:
        def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            assert callable(on_event)
            on_event(span(1, run_id=f"run_{selected.name}"))
            return outcome(selected.name)

        def cancel_active(self) -> None:
            pass

    observer = _SyncEventObserver(cast(Any, Builtin()), None)

    _run_candidates_sync(cast(Any, Transport()), candidates, observer)

    assert sorted(observed) == [("gpt", "run_gpt"), ("opus", "run_opus")]


def test_async_candidate_runner_uses_one_bound_observer_per_run() -> None:
    candidates = (candidate("opus"), candidate("gpt"))
    observed: list[tuple[str, str]] = []

    class Builtin:
        def observe(self, selected: Candidate, event: sf.Event) -> None:
            observed.append((selected.name, event.run_id))

    class Transport:
        async def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            assert callable(on_event)
            await cast(Any, on_event)(span(1, run_id=f"run_{selected.name}"))
            return outcome(selected.name)

        async def cancel_active(self) -> None:
            pass

    observer = _AsyncEventObserver(cast(Any, Builtin()), None)

    asyncio.run(_run_candidates_async(cast(Any, Transport()), candidates, observer))

    assert sorted(observed) == [("gpt", "run_gpt"), ("opus", "run_opus")]


def test_final_report_is_the_only_score_and_finished_authority() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)
    progress.observe(
        opus,
        sf.events.Started(
            id="started",
            run_id="run_opus",
            sequence=1,
            timestamp=_START,
            source="/trace/run_opus/node/root",
            url4=opus.url4,
        ),
    )
    progress.observe(opus, span(2, run_id="run_opus"))
    progress.observe(
        opus,
        sf.events.Terminated(
            id="terminated",
            run_id="run_opus",
            sequence=3,
            timestamp=_START + timedelta(seconds=2),
            source="/trace/run_opus/node/root",
            status="succeeded",
        ),
    )

    assert progress.rows[0].status == "running"
    assert progress.rows[0].score is None
    assert progress.rows[0].score_available is False

    progress.reconcile(report_for(opus))

    assert progress.rows[0].status == "finished"
    assert progress.rows[0].score == 0.75
    assert progress.rows[0].score_available is True
    assert progress.rows[0].cost_usd == Decimal("0.40")


@pytest.mark.parametrize(
    ("started", "error", "expected"),
    [
        (False, RuntimeError("submission failed"), "not_run"),
        (True, KeyboardInterrupt(), "stopped"),
        (True, TimeoutError(), "timed_out"),
        (True, RuntimeError("decode failed"), "run_failed"),
    ],
)
def test_abort_maps_only_explicit_workflow_evidence(
    started: bool,
    error: BaseException,
    expected: str,
) -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)
    if started:
        progress.observe(
            opus,
            sf.events.Started(
                id="started",
                run_id="run_opus",
                sequence=1,
                timestamp=_START,
                source="/trace/run_opus/node/root",
                url4=opus.url4,
            ),
        )

    progress.abort(error)

    assert progress.rows[0].status == expected


def test_terminal_engine_evidence_wins_over_workflow_abort_inference() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)
    root = "/trace/run_opus/node/root"
    progress.observe(
        opus,
        sf.events.Started(
            id="started",
            run_id="run_opus",
            sequence=1,
            timestamp=_START,
            source=root,
            url4=opus.url4,
        ),
    )
    progress.observe(
        opus,
        sf.events.Terminated(
            id="terminated",
            run_id="run_opus",
            sequence=2,
            timestamp=_START + timedelta(seconds=1),
            source=root,
            status="stopped",
        ),
    )

    progress.abort(RuntimeError("decode failed"))

    assert progress.rows[0].status == "stopped"


@pytest.mark.parametrize("phase", ["reconcile", "abort"])
def test_broken_terminal_progress_phase_still_closes_the_observer(phase: str) -> None:
    opus = candidate("opus")

    class BrokenProgress:
        closed = False

        def reconcile(self, report: sf.Report) -> None:
            del report
            raise RuntimeError("render failed")

        def abort(self, error: BaseException) -> None:
            del error
            raise RuntimeError("render failed")

        def close(self) -> None:
            self.closed = True

    progress = BrokenProgress()
    observer = _SyncEventObserver(cast(Any, progress), None)

    if phase == "reconcile":
        _reconcile_event_observer(observer, report_for(opus))
    else:
        _abort_event_observer(observer, RuntimeError("run failed"))

    assert progress.closed is True


def test_candidate_table_uses_the_approved_columns_and_truthful_values() -> None:
    opus = candidate("opus")
    gpt = candidate("gpt")
    progress = _EvaluationProgress(candidates=(opus, gpt), case_count=100)
    progress.observe(opus, span(1, run_id="run_opus"))

    html = evaluation_panel_html(progress, "DRACO")

    headers = ["Candidate", "Status", "Progress", "Score", "Cost", "Cache"]
    positions = [html.index(f">{header}<") for header in headers]
    assert positions == sorted(positions)
    assert "<table" in html
    assert "sf-eval__table-wrap" in html
    assert "overflow-x:auto" in html
    assert "opus" in html
    assert "gpt" in html
    assert "1 / 100" in html
    assert "Not scored yet" in html
    assert "Not reported" in html


def test_candidate_table_has_no_inferred_phase_gradient_or_whole_table_live_region() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)

    html = evaluation_panel_html(progress, "DRACO")

    assert "Answering" not in html
    assert "Grading" not in html
    assert "linear-gradient" not in html
    assert "sf-eval-sweep" not in html
    table = html.split("<table", 1)[1].split("</table>", 1)[0]
    assert "aria-live" not in table
    assert "prefers-reduced-motion:reduce" in html


def test_opaque_url4_replay_keeps_an_unknown_denominator_truthful() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=None)
    progress.observe(opus, span(1, run_id="run_opus"))

    html = evaluation_panel_html(progress, "URL4 replay")

    assert "1 case finished" in html
    assert "max='None'" not in html
    assert "1 /" not in html


def test_notebook_view_clock_advances_and_abort_leaves_a_frozen_panel(
    monkeypatch: Any,
) -> None:
    from screamingface._ui.evaluation_view import _NotebookEvaluationView

    class HTML:
        def __init__(self, *, value: str) -> None:
            self.value = value

    monkeypatch.setitem(sys.modules, "ipywidgets", SimpleNamespace(HTML=HTML))
    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    opus = candidate("opus")
    now = [100.0]
    view = _NotebookEvaluationView(
        (opus,),
        1,
        "DRACO",
        clock=lambda: now[0],
        tick=False,
    )
    view.observe(
        opus,
        sf.events.Started(
            id="started",
            run_id="run_opus",
            sequence=1,
            timestamp=_START,
            source="/trace/run_opus/node/root",
            url4=opus.url4,
        ),
    )

    assert "0.0s" in view._html.value

    now[0] += 45
    view._html.value = view._render()

    assert "45.0s" in view._html.value

    view.abort(RuntimeError("result decode failed"))

    assert view._done.is_set()
    assert "Run failed" in view._html.value
    assert "result decode failed" in view._html.value
