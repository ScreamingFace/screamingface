"""OME-1193 — the declared answer seed reaches the wire AND the report the researcher keeps.

FEATURE: a variance study runs the same exam N times with N seeds; each `report.json`
must name its sitting, or the raw data is unlabeled and provenance lives in shell
history. The seed makes two journeys from one `evaluate(answer_seed=…)` kwarg:

    wire:   Client.evaluate ──► transport.run ──► GET / with `X-Answer-Seed` (engine
            stamps every answer call — OME-1038, engine side)
    record: Client.evaluate ──► report_from_outcomes ──► CandidateResult.answer_seed
            ──► report.to_json() / report.json

INVARIANT: absence is the default. No kwarg ⇒ no header on the wire AND the fake
transport is called exactly as before (no new kwarg), so every prior transport fake
stays valid — the SDK mirror of the engine's byte-identity rule.

INVARIANT: the serialized report always carries the `answer_seed` key (null when
undeclared) — the report's own convention is stable keys with null for unavailable
values (see `test_report_json_marks_unavailable_usage_fields_as_null`), never a key
that appears only sometimes.
"""

from __future__ import annotations

import json

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport
from test_report import benchmark, case_results, report

import screamingface as sf
from screamingface._engine.transport import _start_sync
from screamingface._evaluation.model import _compiled_operation

TOKEN = "cap-token"
URL4 = "(@)!'go'"


# --- the wire: the run-start request carries the header ---------------------------------------


def _recording_http(seen: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            202,
            headers={"Preference-Applied": "respond-async", "Location": "/runs/1"},
        )

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://engine.test")


def test_a_declared_seed_is_sent_as_the_answer_seed_header() -> None:
    seen: list[httpx.Request] = []

    _start_sync(_recording_http(seen), TOKEN, URL4, answer_seed=7)

    assert seen[0].headers["X-Answer-Seed"] == "7"


def test_an_undeclared_seed_sends_no_header_at_all() -> None:
    """The engine reads absence as 'unseeded run'; a default here would seed every run."""
    seen: list[httpx.Request] = []

    _start_sync(_recording_http(seen), TOKEN, URL4)

    assert "X-Answer-Seed" not in seen[0].headers


# --- the record: CandidateResult carries and serializes the sitting ---------------------------


def candidate(name: str, *, answer_seed: int | None = None) -> sf.CandidateResult:
    """A minimal scored record — local so `test_report`'s own fixture stays untouched."""
    from datetime import UTC, datetime

    cases = case_results()
    return sf.CandidateResult(
        benchmark=benchmark(),
        run_id=f"run_{name}",
        started_at=datetime(2026, 9, 14, 9, 0, tzinfo=UTC),
        completed_at=datetime(2026, 9, 14, 9, 0, 1, tzinfo=UTC),
        name=name,
        kind="model",
        url4=f"(@)!'{name}'",
        models=(f"provider/{name}",),
        operations=(
            _compiled_operation(
                id=f"op_{name}", kind="model", label=f"{name} answer", depends_on=()
            ),
        ),
        score=0.5,
        coverage=1.0,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
        answer_seed=answer_seed,
    )


def test_the_report_record_carries_a_declared_seed_into_portable_json() -> None:
    value = candidate("gpt", answer_seed=7)

    assert value.answer_seed == 7
    assert value.to_dict()["answer_seed"] == 7
    assert json.loads(report(value).to_json())["candidates"][0]["answer_seed"] == 7


def test_an_unseeded_record_serializes_answer_seed_as_null() -> None:
    """Stable key, null value — the report's convention for 'not available', so a reader
    never has to distinguish 'old report' from 'unseeded run' by key presence."""
    value = candidate("gpt")

    assert value.answer_seed is None
    assert value.to_dict()["answer_seed"] is None


@pytest.mark.parametrize("bad", [True, "7", 7.0])
def test_the_record_rejects_a_non_integer_seed(bad: object) -> None:
    """`bool` is an `int` subclass — accepted, it would serialize as `true` and claim a
    sitting no engine run can have."""
    with pytest.raises(TypeError):
        candidate("gpt", answer_seed=bad)  # type: ignore[arg-type]


def test_a_negative_seed_is_a_legal_sitting() -> None:
    """Provider seeds are arbitrary integers (OME-585) — no range narrowing in the record."""
    assert candidate("gpt", answer_seed=-5).to_dict()["answer_seed"] == -5


# --- end to end: evaluate() threads the seed to the transport and into the report -------------


def _client(transport: _ReplayTransport) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    )


def test_evaluate_threads_the_seed_to_the_transport_and_the_report() -> None:
    """The seed rides the Candidate the transport already receives — the run-transport
    protocol (and every fake implementing it) is deliberately untouched."""
    transport = _ReplayTransport()

    with _client(transport) as client:
        result = client.evaluate(REPLAY_URL4, progress=False, answer_seed=7)

    assert transport.candidate is not None
    assert transport.candidate.answer_seed == 7
    assert result.candidates[0].answer_seed == 7
    assert json.loads(result.to_json())["candidates"][0]["answer_seed"] == 7


def test_evaluate_without_a_seed_hands_the_transport_an_unseeded_candidate() -> None:
    transport = _ReplayTransport()

    with _client(transport) as client:
        result = client.evaluate(REPLAY_URL4, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.answer_seed is None
    assert result.candidates[0].answer_seed is None


@pytest.mark.parametrize("bad", [True, "7", 7.0])
def test_evaluate_rejects_a_non_integer_seed_before_any_call(bad: object) -> None:
    transport = _ReplayTransport()

    with _client(transport) as client, pytest.raises(TypeError):
        client.evaluate(REPLAY_URL4, progress=False, answer_seed=bad)  # type: ignore[arg-type]

    assert transport.candidate is None
