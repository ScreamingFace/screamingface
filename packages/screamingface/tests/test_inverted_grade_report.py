"""OME-1400 — report.json marks a Benchmark whose scores are already 1 − the eval's grade.

FEATURE: safety Benchmarks where refusing is the right answer. A researcher holding only a
report.json must see that its Benchmark is scored by refusal rate — not a compliance rate —
so the ``benchmark`` block says ``"inverted_grade": true``. The mark travels on two wires:

    normal run:  GET /v1/benchmarks/{id} ──► BenchmarkInfo ──► report.json
                 (the run result must agree — a mismatch is a broken Engine, refused)
    replay:      run result only ──► BenchmarkInfo ──► report.json

INVARIANT: the report's own convention is a stable key (see the ``answer_seed`` suite), so
every report states ``inverted_grade`` — ``false`` for an ordinary Benchmark. The WIRE keeps
the Engine's "absent unless true" rule, so an absent key reads as ``False``.

INVARIANT: the mark is information, never an instruction — no SDK code flips a score with it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import Any, cast

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport
from test_draco_vertical_slice import _case_payload, _FakeTransport
from test_draco_vertical_slice import _engine as _draco_engine

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface.errors import ExecutionError


def _result_payload(**extra: object) -> dict[str, object]:
    """The draco fixture's run result, optionally carrying the Engine's mark."""

    return {
        "schema": "screamingface.candidate-result.v1",
        "benchmark_id": "draco",
        "benchmark_revision": "fixture-revision",
        "case_count": 1,
        "score": 0.7,
        "coverage": 1.0,
        "metrics": {},
        "cases": [_case_payload(score=0.7)],
        "failures": [],
        **extra,
    }


def _marked_engine(request: httpx.Request) -> httpx.Response:
    """The draco fixture Engine, publishing its Benchmark resource with the mark."""

    response: httpx.Response = _draco_engine(request)
    if request.url.path != "/v1/benchmarks/draco":
        return response
    return httpx.Response(200, json={**response.json(), "inverted_grade": True})


def _evaluate(engine: Any, transport: _FakeTransport) -> sf.Report:
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine),
        run_transport=transport,
    )
    with client:
        return client.evaluate(
            sf.Model("anthropic/claude-haiku-4-5", name="haiku"),
            benchmark="draco",
            limit=1,
            progress=False,
        )


def _benchmark_blocks(report: sf.Report) -> list[dict[str, Any]]:
    """The root ``benchmark`` block and every candidate's copy, as report.json writes them."""

    written: dict[str, Any] = json.loads(report.to_json())
    return [written["benchmark"], *(entry["benchmark"] for entry in written["candidates"])]


# ── normal runs: the Benchmark resource carries the mark ─────────────────────────


def test_a_flipped_benchmarks_report_json_carries_the_mark() -> None:
    report = _evaluate(_marked_engine, _FakeTransport(_result_payload(inverted_grade=True)))

    assert report.benchmark.inverted_grade is True
    assert [block["inverted_grade"] for block in _benchmark_blocks(report)] == [True, True]


def test_an_ordinary_benchmarks_report_json_states_false() -> None:
    """Stable key: an ordinary Benchmark's report says ``false``, it never omits the key."""

    report = _evaluate(_draco_engine, _FakeTransport(_result_payload()))

    assert report.benchmark.inverted_grade is False
    assert [block["inverted_grade"] for block in _benchmark_blocks(report)] == [False, False]


@pytest.mark.parametrize(
    ("engine", "result_extra"),
    [
        (_marked_engine, {}),  # resource says flipped, run result doesn't
        (_draco_engine, {"inverted_grade": True}),  # run result says flipped, resource doesn't
    ],
)
def test_a_resource_and_result_that_disagree_are_refused(
    engine: Any, result_extra: dict[str, object]
) -> None:
    """The two wires describe ONE Benchmark revision; disagreement means a broken Engine,
    and a report that guessed would publish the wrong meaning for every score."""

    with pytest.raises(ExecutionError) as caught:
        _evaluate(engine, _FakeTransport(_result_payload(**result_extra)))

    chain: str = f"{caught.value} {caught.value.__cause__}"
    assert "inverted_grade" in chain


def test_a_non_boolean_mark_in_the_run_result_is_refused() -> None:
    with pytest.raises(ExecutionError) as caught:
        _evaluate(_marked_engine, _FakeTransport(_result_payload(inverted_grade="yes")))

    assert "inverted_grade" in f"{caught.value} {caught.value.__cause__}"


# ── replays: the run result is the only source ───────────────────────────────────


class _MarkedReplayTransport(_ReplayTransport):
    """The replay fixture, with the Engine's mark on its run result."""

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        outcome: _RunOutcome = super().run(candidate, on_event)
        assert outcome.result_body is not None
        body: dict[str, Any] = json.loads(outcome.result_body)
        body["inverted_grade"] = True
        return _RunOutcome(
            run_id=outcome.run_id,
            started_at=outcome.started_at,
            completed_at=outcome.completed_at,
            result_body=json.dumps(body),
            media_type=outcome.media_type,
            root_usage=outcome.root_usage,
        )


def _replayed(transport: _ReplayTransport) -> sf.Report:
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    )
    with client:
        return client.evaluate(REPLAY_URL4, progress=False)


def test_a_replayed_report_json_carries_the_mark_from_the_run_result() -> None:
    """A replay never loads the Benchmark resource — the run result must be enough."""

    report = _replayed(_MarkedReplayTransport())

    assert [block["inverted_grade"] for block in _benchmark_blocks(report)] == [True, True]


def test_a_replay_of_an_ordinary_benchmark_states_false() -> None:
    report = _replayed(_ReplayTransport())

    assert [block["inverted_grade"] for block in _benchmark_blocks(report)] == [False, False]


# ── the record itself ────────────────────────────────────────────────────────────


def test_benchmark_info_defaults_to_an_ordinary_benchmark() -> None:
    assert sf.BenchmarkInfo(id="draco", revision="r", case_count=1).inverted_grade is False


@pytest.mark.parametrize("bad", ["true", 1, None])
def test_benchmark_info_refuses_a_non_boolean_mark(bad: object) -> None:
    with pytest.raises(TypeError, match="inverted_grade"):
        sf.BenchmarkInfo(id="draco", revision="r", case_count=1, inverted_grade=bad)  # type: ignore[arg-type]


# ── the notebook helper that reloads a saved report.json ─────────────────────────


def test_the_notebook_reload_helper_keeps_the_mark(tmp_path: Path) -> None:
    """``examples/helpers.py`` rebuilds a Candidate from report.json for a later submit.

    WHY: it reads the ``benchmark`` block back, so dropping the key would turn a refusal
    rate into an ordinary score the moment a researcher reloads their own run.
    """

    report = _evaluate(_marked_engine, _FakeTransport(_result_payload(inverted_grade=True)))
    artifact = report.export(tmp_path / "flipped.json")
    helper = Path(__file__).parents[1] / "examples" / "helpers.py"
    load_candidate_result = cast(
        Callable[..., sf.CandidateResult], run_path(str(helper))["load_candidate_result"]
    )

    assert load_candidate_result(str(artifact)).benchmark.inverted_grade is True
