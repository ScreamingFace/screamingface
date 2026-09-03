"""Public-workflow regressions for partial Leaderboard Score advisories."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path
from typing import Any, Literal, cast

import httpx
import pytest

import screamingface as sf
from screamingface import _default_client
from screamingface._evaluation.model import _compiled_operation

_SCORE_ID = "af95892d-7438-4ac3-9b47-5e06f62c8251"
_MESSAGE = (
    "Partial submission. This score is based on fewer benchmark cases and is not directly "
    "comparable with a full-run score."
)


def _score_response() -> dict[str, object]:
    return {
        "id": _SCORE_ID,
        "version": 1,
        "benchmark_id": "draco",
        "spec_id": "fusion/alpha",
        "url4_expression": "(@)!'fusion alpha'",
        "submitted_by": "researcher@example.com",
        "submitted_at": "2026-08-08T12:30:00Z",
        "score": 0.5,
        "total_questions": 2,
        "correct_questions": 1,
        "ran_with_providers": ["openrouter"],
        "ran_at_local": "2026-08-08T12:00:00Z",
        "client_name": "screamingface",
        "client_version": "0.1.0",
        "client_platform": "darwin",
        "verified_by_screamingface": False,
        "metadata": {"benchmark_revision": "fixture-revision"},
    }


def _case(case_id: int, score: float | None) -> sf.CaseResult:
    failures = (
        ()
        if score is not None
        else (
            sf.Failure(
                stage="grading",
                code="fixture_ungraded",
                message="the fixture Case could not be graded",
                case_id=case_id,
            ),
        )
    )
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=f"Answer {case_id}",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=score, metrics={}, checks=()),
        failures=failures,
        metadata={},
    )


def _candidate(
    *,
    benchmark_case_count: int = 3,
    case_scores: tuple[float | None, ...] = (1.0, 0.0),
) -> sf.CandidateResult:
    return sf.CandidateResult(
        benchmark=sf.BenchmarkInfo(
            id="draco",
            revision="fixture-revision",
            case_count=benchmark_case_count,
        ),
        run_id="run-fusion-alpha",
        started_at=datetime(2026, 8, 8, 11, 59, tzinfo=UTC),
        completed_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
        name="fusion/alpha",
        kind="model",
        url4="(@)!'fusion alpha'",
        models=("openrouter/model-a",),
        operations=(_compiled_operation(id="op-a", kind="model", label="a", depends_on=()),),
        score=0.5,
        coverage=round(sum(score is not None for score in case_scores) / len(case_scores), 4),
        metrics={"accuracy": 0.5},
        cases=tuple(_case(index, score) for index, score in enumerate(case_scores, start=1)),
        members=(),
        failures=(),
        usage=sf.Usage(),
    )


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(handler),
    )


def _async_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(handler),
    )


def test_documented_submit_warns_at_each_user_call_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """README usage must identify distinct user lines, not one SDK wrapper line."""

    candidate = _candidate()
    with _client(lambda _request: httpx.Response(201, json=_score_response())) as client:
        monkeypatch.setattr(_default_client, "_client", client)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default", sf.EvaluationWarning)
            sf.leaderboards.submit(candidate)
            sf.leaderboards.submit(candidate)
            sf.leaderboards.submit(candidate)

    assert [str(item.message) for item in caught] == [_MESSAGE, _MESSAGE, _MESSAGE]
    assert all(item.category is sf.EvaluationWarning for item in caught)
    assert all(item.filename == __file__ for item in caught)
    assert len({item.lineno for item in caught}) == 3


def test_incomplete_grading_warns_and_preserves_the_submission_payload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _client(handler) as client, pytest.warns(sf.EvaluationWarning) as caught:
        submitted = client.leaderboards.submit(
            _candidate(benchmark_case_count=2, case_scores=(1.0, None))
        )

    assert str(caught[0].message) == _MESSAGE
    assert submitted.id.hex == _SCORE_ID.replace("-", "")
    assert len(seen) == 1
    payload = seen[0].read().decode()
    assert '"total_questions":2' in payload
    assert "partial_submission" not in payload
    assert "notice" not in payload


@pytest.mark.asyncio
async def test_async_submit_has_the_same_partial_warning_and_post_behavior() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    async with _async_client(handler) as client:
        with pytest.warns(sf.EvaluationWarning) as caught:
            submitted = await client.leaderboards.submit(_candidate())

    assert str(caught[0].message) == _MESSAGE
    assert submitted.id.hex == _SCORE_ID.replace("-", "")
    assert len(seen) == 1


def test_full_submission_emits_no_partial_advisory() -> None:
    with (
        _client(lambda _request: httpx.Response(201, json=_score_response())) as client,
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("error", sf.EvaluationWarning)
        client.leaderboards.submit(_candidate(benchmark_case_count=2))


def test_case_count_must_equal_the_benchmark_even_when_it_is_defensively_over() -> None:
    with (
        _client(lambda _request: httpx.Response(201, json=_score_response())) as client,
        pytest.warns(sf.EvaluationWarning) as caught,
    ):
        client.leaderboards.submit(_candidate(benchmark_case_count=1))

    assert str(caught[0].message) == _MESSAGE


def test_warning_as_error_prevents_the_post_before_the_scoreboard_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _client(handler) as client:
        monkeypatch.setattr(_default_client, "_client", client)
        with (
            warnings.catch_warnings(),
            pytest.raises(sf.EvaluationWarning, match="Partial submission"),
        ):
            warnings.simplefilter("error", sf.EvaluationWarning)
            sf.leaderboards.submit(_candidate())

    assert seen == []


@pytest.mark.asyncio
async def test_async_warning_as_error_also_prevents_the_post() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    async with _async_client(handler) as client:
        with (
            warnings.catch_warnings(),
            pytest.raises(sf.EvaluationWarning, match="Partial submission"),
        ):
            warnings.simplefilter("error", sf.EvaluationWarning)
            await client.leaderboards.submit(_candidate())

    assert seen == []


def test_documented_saved_result_loader_preserves_partial_detection(tmp_path: Path) -> None:
    candidate = _candidate()
    artifact = sf.Report(
        benchmark=candidate.benchmark,
        case_count=2,
        candidates=(candidate,),
    ).export(tmp_path / "partial.json")
    helper = Path(__file__).parents[1] / "examples" / "helpers.py"
    load_candidate_result = cast(
        Callable[..., sf.CandidateResult], run_path(str(helper))["load_candidate_result"]
    )

    reloaded = load_candidate_result(str(artifact))

    assert len(reloaded.cases) == 2
    assert reloaded.benchmark.case_count == 3
    with (
        _client(lambda _request: httpx.Response(201, json=_score_response())) as client,
        pytest.warns(sf.EvaluationWarning) as caught,
    ):
        client.leaderboards.submit(reloaded)
    assert str(caught[0].message) == _MESSAGE


def _run_notebook_cell(
    monkeypatch: pytest.MonkeyPatch,
    client: sf.Client,
    source: str,
    *,
    candidate: sf.CandidateResult,
    filter_action: Literal["default", "error", "ignore"] = "default",
) -> tuple[Any, Any]:
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output

    from screamingface._scoreboard import submission_notice

    monkeypatch.setattr(submission_notice, "running_in_notebook", lambda: True)
    monkeypatch.setattr(_default_client, "_client", client)
    shell = InteractiveShell.instance()
    monkeypatch.setitem(shell.user_ns, "sf", sf)
    monkeypatch.setitem(shell.user_ns, "candidate", candidate)
    with warnings.catch_warnings(), capture_output(display=True) as captured:
        warnings.simplefilter(filter_action, sf.EvaluationWarning)
        execution = shell.run_cell(source)
    return execution, captured


def test_notebook_assignment_displays_one_accessible_branded_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(lambda _request: httpx.Response(201, json=_score_response())) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "saved_score = sf.leaderboards.submit(candidate)",
            candidate=_candidate(),
        )

    assert execution.success is True
    assert len(captured.outputs) == 1
    html = captured.outputs[0].data["text/html"]
    assert "Partial submission" in html
    assert "not directly comparable with a full-run score" in html
    assert "role='alert'" in html
    assert "data-notice-code='partial_submission'" in html
    assert "data-notice-severity='warning'" in html


def test_notebook_final_expression_does_not_repeat_the_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(lambda _request: httpx.Response(201, json=_score_response())) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "sf.leaderboards.submit(candidate)",
            candidate=_candidate(),
        )

    assert execution.success is True
    assert len(captured.outputs) == 1
    assert "Partial submission" in captured.outputs[0].data["text/html"]
    score_html = cast(Any, execution.result)._repr_html_()
    assert "Score published" in score_html
    assert "Partial submission" not in score_html


def test_notebook_full_submission_displays_no_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(lambda _request: httpx.Response(201, json=_score_response())) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "saved_score = sf.leaderboards.submit(candidate)",
            candidate=_candidate(benchmark_case_count=2),
        )

    assert execution.success is True
    assert captured.outputs == []


def test_notebook_failed_submission_displays_no_success_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(lambda _request: httpx.Response(500, json={"detail": "unavailable"})) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "saved_score = sf.leaderboards.submit(candidate)",
            candidate=_candidate(),
        )

    assert execution.success is False
    assert isinstance(execution.error_in_exec, sf.LeaderboardError)
    assert captured.outputs == []


@pytest.mark.asyncio
async def test_async_notebook_submission_displays_the_same_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from IPython.utils.capture import capture_output

    from screamingface._scoreboard import submission_notice

    monkeypatch.setattr(submission_notice, "running_in_notebook", lambda: True)
    async with _async_client(
        lambda _request: httpx.Response(201, json=_score_response())
    ) as client:
        with warnings.catch_warnings(), capture_output(display=True) as captured:
            warnings.simplefilter("default", sf.EvaluationWarning)
            submitted = await client.leaderboards.submit(_candidate())

    assert submitted.id.hex == _SCORE_ID.replace("-", "")
    assert len(captured.outputs) == 1
    assert "Partial submission" in captured.outputs[0].data["text/html"]


def test_notebook_warning_as_error_prevents_the_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: the advisory policy is uniform — a notebook is not an escape hatch."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _client(handler) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "saved_score = sf.leaderboards.submit(candidate)",
            candidate=_candidate(),
            filter_action="error",
        )

    assert execution.success is False
    assert isinstance(execution.error_in_exec, sf.EvaluationWarning)
    assert seen == []
    assert captured.outputs == []


def test_notebook_ignored_warning_suppresses_the_branded_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: a researcher running deliberate limit=N sweeps must be able to opt out."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _client(handler) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "saved_score = sf.leaderboards.submit(candidate)",
            candidate=_candidate(),
            filter_action="ignore",
        )

    assert execution.success is True
    assert len(seen) == 1
    assert captured.outputs == []


def test_notebook_default_policy_shows_the_notice_and_nothing_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: the branded notice replaces Python's red block, it does not accompany it."""

    with _client(lambda _request: httpx.Response(201, json=_score_response())) as client:
        execution, captured = _run_notebook_cell(
            monkeypatch,
            client,
            "saved_score = sf.leaderboards.submit(candidate)",
            candidate=_candidate(),
            filter_action="default",
        )

    assert execution.success is True
    assert len(captured.outputs) == 1
    assert "Partial submission" in captured.outputs[0].data["text/html"]
    assert captured.stderr == ""


def test_one_ungraded_case_is_partial_even_when_coverage_rounds_to_one() -> None:
    """INVARIANT: coverage is a 4-dp wire metric; the Cases themselves are the authority.

    WHY: the Engine reports round(gradeable / case_count, 4), so on a large Benchmark a
    handful of missing grades rounds to exactly 1.0 and would read as a complete run.
    """

    graded = (1.0,) * 19_999
    candidate = _candidate(benchmark_case_count=20_000, case_scores=(*graded, None))

    assert candidate.coverage == 1.0
    with (
        _client(lambda _request: httpx.Response(201, json=_score_response())) as client,
        pytest.warns(sf.EvaluationWarning) as caught,
    ):
        client.leaderboards.submit(candidate)

    assert str(caught[0].message) == _MESSAGE


def test_notebook_display_failure_cannot_hide_an_already_saved_score(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """INVARIANT: rich display is presentation, never authority over a persisted write."""

    from screamingface._scoreboard import submission_notice

    def broken_display(_notice: object) -> None:
        raise RuntimeError("display publisher closed")

    monkeypatch.setattr(submission_notice, "running_in_notebook", lambda: True)
    monkeypatch.setattr(submission_notice, "display_notebook_notice", broken_display)

    with _client(lambda _request: httpx.Response(201, json=_score_response())) as client:
        submitted = client.leaderboards.submit(_candidate())

    assert submitted.id.hex == _SCORE_ID.replace("-", "")
    assert capsys.readouterr().err == _MESSAGE + "\n"
