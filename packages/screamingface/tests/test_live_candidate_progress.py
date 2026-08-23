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
from screamingface._ui.style import FUSION_GRADIENT, STYLE

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


def report_for(
    selected: Candidate,
    *,
    score: float | None = 0.75,
    case_count: int = 1,
    cost_usd: Decimal | None = Decimal("0.40"),
    graded_case_count: int | None = None,
    completed_seconds: int = 2,
) -> sf.Report:
    numeric_grades = (
        (case_count if graded_case_count is None else graded_case_count) if score is not None else 0
    )
    cases = tuple(
        sf.CaseResult(
            case_id=case_id,
            input="Question",
            output="Answer",
            finish_reason="stop",
            grade=(
                sf.CaseGrade(method="fixture", score=score, metrics={}, checks=())
                if score is None or case_id <= numeric_grades
                else None
            ),
            failures=(
                ()
                if score is None or case_id <= numeric_grades
                else (
                    sf.Failure(
                        stage="grading",
                        code="missing_grade",
                        message="fixture grade unavailable",
                        case_id=case_id,
                        metadata={},
                    ),
                )
            ),
            metadata={},
        )
        for case_id in range(1, case_count + 1)
    )
    benchmark = sf.BenchmarkInfo(id="draco", revision="fixture", case_count=100)
    result = sf.CandidateResult(
        benchmark=benchmark,
        run_id=f"run_{selected.name}",
        started_at=_START,
        completed_at=_START + timedelta(seconds=completed_seconds),
        name=selected.name,
        kind=selected.kind,
        url4=selected.url4,
        models=selected.models,
        operations=selected.operations,
        score=score,
        coverage=round(numeric_grades / case_count, 4),
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=sf.Usage(
            input_tokens=1_000,
            output_tokens=200,
            cost_usd=cost_usd,
        ),
    )
    return sf.Report(benchmark=benchmark, case_count=case_count, candidates=(result,))


def test_sync_candidate_runner_uses_one_bound_observer_per_run() -> None:
    candidates = (candidate("opus"), candidate("gpt"))
    begun: list[str] = []
    observed: list[tuple[str, str]] = []

    class Builtin:
        def begin(self, selected: Candidate) -> None:
            begun.append(selected.name)

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

    assert sorted(begun) == ["gpt", "opus"]
    assert sorted(observed) == [("gpt", "run_gpt"), ("opus", "run_opus")]


def test_async_candidate_runner_uses_one_bound_observer_per_run() -> None:
    candidates = (candidate("opus"), candidate("gpt"))
    begun: list[str] = []
    observed: list[tuple[str, str]] = []

    class Builtin:
        def begin(self, selected: Candidate) -> None:
            begun.append(selected.name)

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

    assert sorted(begun) == ["gpt", "opus"]
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


def test_final_report_reconciles_case_progress_without_erasing_live_cost() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=None)
    progress.observe(opus, span(1, run_id="run_opus"))
    progress.observe(opus, span(2, run_id="run_opus"))
    progress.observe(opus, span(3, run_id="run_opus"))
    progress.observe(
        opus,
        sf.events.Usage(
            id="usage",
            run_id="run_opus",
            sequence=4,
            timestamp=_START,
            source="/trace/run_opus/node/root",
            scope="self",
            provider="provider",
            model="opus",
            pricing_version="v1",
            usage=sf.Usage(cost_usd=Decimal("0.25")),
        ),
    )

    progress.reconcile(report_for(opus, case_count=2, cost_usd=None))

    row = progress.rows[0]
    assert (row.completed_cases, row.total_cases) == (2, 2)
    assert row.cost_usd == Decimal("0.25")


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


def test_submitted_candidate_without_lifecycle_evidence_is_not_labelled_not_run() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)

    progress.begin(opus)
    progress.abort(RuntimeError("event stream ended"))

    assert progress.rows[0].status == "run_failed"
    assert progress.rows[0].activity == "Run outcome unavailable"


def test_bound_started_event_does_not_depend_on_repeating_the_candidate_url4() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)

    progress.begin(opus)
    progress.observe(
        opus,
        sf.events.Started(
            id="started",
            run_id="run_opus",
            sequence=1,
            timestamp=_START,
            source="/trace/run_opus/node/root",
            url4="(@)!'wire-normalized-differently'",
        ),
    )

    assert progress.rows[0].status == "running"


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

    html = evaluation_panel_html(progress, "DRACO", elapsed=20)
    table = html.split("<table", 1)[1].split("</table>", 1)[0]
    assert ">Stopped<" in table
    assert "Run stopped" not in table
    assert "sf-eval__activity" not in table
    assert "<details" not in html
    assert "Run stopped" not in html


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

    headers = ["Candidate", "Status", "Cases", "Score", "Cost", "Cache hit"]
    positions = [html.index(f">{header}<") for header in headers]
    assert positions == sorted(positions)
    assert "<table" in html
    assert "sf-eval__table-wrap" in html
    assert "overflow-x:auto" not in html
    assert "min-width:820px" not in html
    assert "tabindex='0'" not in html
    assert "table-layout:fixed" in html
    assert ".sf-eval{border:0;padding:4px 0 14px;" in html
    widths = {"candidate": 27, "status": 17, "cases": 10, "score": 17, "cost": 14, "cache": 15}
    for name, width in widths.items():
        assert f".sf-eval__col--{name}{{width:{width}%}}" in html
    assert "opus" in html
    assert "gpt" in html
    assert "provider/opus" not in html
    assert "provider/gpt" not in html
    assert "<progress" not in html
    assert "1 / 100" in html
    assert "Not scored yet" in html
    assert "Not reported" in html


def test_numeric_candidate_columns_are_right_aligned() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)

    html = evaluation_panel_html(progress, "DRACO")

    for header in ("Cases", "Score", "Cost", "Cache hit"):
        assert f"<th scope='col' class='sf-eval__num'>{header}</th>" in html
    assert ".sf-eval__num{text-align:right}" in html
    row = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert row.count("sf-eval__num") == 4


def test_notebook_surface_uses_current_sfds_v2_tokens() -> None:
    assert "--sf-bg:#fcfdff" in STYLE
    assert "--sf-surface:#f4f6f9" in STYLE
    assert "--sf-surface-2:#eceef0" in STYLE
    assert "--sf-ink:#3b3c3e" in STYLE
    assert "--sf-ink-2:#616265" in STYLE
    assert "--sf-ink-3:#b4b6b8" in STYLE
    assert "--sf-line:#cdcfd2" in STYLE
    assert "--sf-line-2:#b4b6b8" in STYLE
    assert "--sf-danger-solid:#ff0325" in STYLE
    assert "--sf-bg:#05070b" in STYLE
    assert "--sf-surface:#0c0f13" in STYLE
    assert "--sf-surface-2:#15181c" in STYLE
    assert "--sf-ink:#e0e5eb" in STYLE
    assert "--sf-ink-2:#c7ccd2" in STYLE
    assert "--sf-ink-3:#585c61" in STYLE
    assert "--sf-line:#35383d" in STYLE
    assert "--sf-line-2:#585c61" in STYLE
    assert "--sf-danger-solid:#ed413f" in STYLE


def test_candidate_table_matches_current_sfds_table_recipe() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)
    progress.abort(RuntimeError("failed"))

    html = evaluation_panel_html(progress, "DRACO")

    assert "font-size:13px" in html
    assert "padding:12px 16px" in html
    assert "border-bottom:1px solid var(--sf-line-2)" in html
    assert "font-size:11px;font-weight:500" in html
    assert "letter-spacing:.1em" in html
    assert ".sf-eval__candidate{font-family:" in html
    assert "font-weight:500;\n  color:var(--sf-ink)" in html
    assert "align-items:center;gap:8px" in html
    assert "background:var(--sf-danger-solid)" in html


def test_candidate_table_has_no_inferred_phase_or_whole_table_live_region() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)

    html = evaluation_panel_html(progress, "DRACO")

    assert "Answering" not in html
    assert "Grading" not in html
    assert "sf-eval-sweep" not in html
    table = html.split("<table", 1)[1].split("</table>", 1)[0]
    assert "aria-live" not in table
    assert "<progress" not in html


def test_running_panel_has_stable_benchmark_title_and_canonical_static_status() -> None:
    opus = candidate("opus")
    gpt = candidate("gpt")
    progress = _EvaluationProgress(candidates=(opus, gpt), case_count=2)
    progress.begin(opus)
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

    html = evaluation_panel_html(progress, "DRACO", elapsed=45)

    assert "<div class='sf-eval__title'>DRACO</div>" in html
    assert "<div class='sf-eval__title-state'>evaluating… · 0%</div>" in html
    assert ".sf-eval__title-row{display:flex" in html
    assert "justify-content:space-between" in html
    assert "DRACO ·" not in html
    assert "sf-eval__sub" not in html
    assert ".sf-eval__status--running .sf-eval__status-sq{background:var(--sf-accent)}" in html
    assert "@keyframes sf-eval-running" not in html
    assert "animation:sf-eval-running" not in html


def test_overall_progress_uses_canonical_sfds_run_treatment() -> None:
    opus = candidate("opus")
    gpt = candidate("gpt")
    progress = _EvaluationProgress(candidates=(opus, gpt), case_count=100)
    progress.observe(opus, span(1, run_id="run_opus"))
    progress.observe(gpt, span(1, run_id="run_gpt"))

    html = evaluation_panel_html(progress, "DRACO", elapsed=45)

    assert "Overall progress" not in html
    assert "2 / 200 case runs" not in html
    assert "evaluating… · 1%" in html
    assert "evaluating… · 1% · 2/200" not in html
    assert "role='progressbar'" in html
    assert "aria-valuemin='0'" in html
    assert "aria-valuemax='200'" in html
    assert "aria-valuenow='2'" in html
    assert "width:1%" in html
    assert "background-size:10000.0% 100%" in html
    assert f"background-image:{FUSION_GRADIENT}" in html
    assert "transition:width .11s linear" in html
    overall = html.split("<div class='sf-eval__overall'>", 1)[1].split("</div>", 1)[0]
    assert "evaluating…" not in overall


def test_opaque_url4_replay_keeps_an_unknown_denominator_truthful() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=None)
    progress.observe(opus, span(1, run_id="run_opus"))

    html = evaluation_panel_html(progress, "URL4 replay")

    assert "1 case finished" in html
    assert "max='None'" not in html
    assert "1 /" not in html
    assert "<div class='sf-eval__overall'>" not in html
    assert "<div class='sf-eval__title-state'>evaluating…</div>" in html


def test_aborted_evaluation_headline_does_not_claim_completion() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)
    progress.begin(opus)
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

    progress.abort(KeyboardInterrupt())

    html = evaluation_panel_html(progress, "DRACO")
    assert "Evaluation complete" not in html
    assert "Evaluation ended" not in html
    assert "<div class='sf-eval__title'>DRACO</div>" in html
    assert "stopped · 0%" in html
    assert "stopped · 0% · 0/1" not in html
    table = html.split("<table", 1)[1].split("</table>", 1)[0]
    assert "Not scored yet" not in table
    assert ">Not scored<" in table


def test_reconciled_evaluation_uses_complete_progress_state() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=1)

    progress.reconcile(report_for(opus))

    html = evaluation_panel_html(progress, "DRACO")
    assert "<div class='sf-eval__title'>DRACO</div>" in html
    assert "<div class='sf-eval__title-state'>complete · 2s</div>" in html
    assert "complete · 100%" not in html
    assert "<div class='sf-eval__overall'>" not in html
    assert "Finished · 2s" in html


def test_partial_result_names_exact_graded_coverage_and_keeps_final_duration() -> None:
    opus = candidate("opus")
    progress = _EvaluationProgress(candidates=(opus,), case_count=2)

    progress.reconcile(
        report_for(
            opus,
            score=0.3799,
            case_count=2,
            graded_case_count=1,
            completed_seconds=70,
        )
    )

    html = evaluation_panel_html(progress, "DRACO")
    assert "Finished · 1/2 graded · 1m 10s" in html
    assert "Finished · Partial" not in html


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

    assert "0s" in view._html.value

    now[0] += 45
    view._html.value = view._render()

    assert "45s" in view._html.value

    view.abort(RuntimeError("result decode failed"))

    assert view._done.is_set()
    assert "Run failed" in view._html.value
    assert "result decode failed" in view._html.value
