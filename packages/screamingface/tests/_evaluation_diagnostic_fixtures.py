from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import NoReturn

from _model_parameter_fixtures import details as _model_details
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.model_parameters import _decode_model_details
from screamingface._evaluation.benchmark import _BenchmarkResource
from screamingface._evaluation.model import Candidate
from screamingface.discovery import ModelInfo

TRACE_ID = "0123456789abcdef0123456789abcdef"
BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        src(
            RelExpr(path="/provider/judge", context="$answer", intent=text("Grade.")),
            name="grade",
            weight=0.0,
        ),
        intent=text("$grade"),
    )
)
RESOURCE = _BenchmarkResource(
    info=sf.BenchmarkInfo(id="draco", revision="fixture-revision", case_count=1),
    case_count=1,
    url4=BENCHMARK_URL4,
)


class Catalog:
    models = (
        ModelInfo(
            id="provider/opus",
            provider="provider",
            supported_parameters=("max_tokens",),
        ),
    )


class FailingTransport:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        if callable(on_event):
            on_event(started(candidate))
        raise self.error

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class AsyncFailingTransport(FailingTransport):
    async def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        if callable(on_event):
            returned = on_event(started(candidate))
            if inspect.isawaitable(returned):
                await returned
        raise self.error

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


class SuccessfulTransport:
    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        if callable(on_event):
            on_event(started(candidate))
        now = datetime.now(UTC)
        return _RunOutcome(
            run_id="internal-stream-topic",
            started_at=now,
            completed_at=now,
            result_body=json.dumps(
                {
                    "schema": "screamingface.candidate-result.v1",
                    "benchmark_id": "draco",
                    "benchmark_revision": "fixture-revision",
                    "case_count": 1,
                    "score": 1.0,
                    "coverage": 1.0,
                    "metrics": {},
                    "cases": [
                        {
                            "status": "scored",
                            "case_id": 1,
                            "input": "Fixture question",
                            "output": "Fixture answer",
                            "finish_reason": "stop",
                            "refusal": None,
                            "stop_reason": None,
                            "rounds_executed": None,
                            "grade": {
                                "method": "fixture",
                                "score": 1.0,
                                "metrics": {},
                                "checks": [],
                            },
                            "failures": [],
                            "metadata": {},
                        }
                    ],
                    "failures": [],
                }
            ),
            media_type="application/json",
            root_usage=None,
        )

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class PartialTransport(SuccessfulTransport):
    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)
        assert outcome.result_body is not None
        document = json.loads(outcome.result_body)
        document["failures"] = [
            {
                "stage": "grading",
                "code": "case_not_graded",
                "message": "One case could not be graded.",
                "retryable": None,
                "case_id": None,
                "metadata": {},
            }
        ]
        return replace(outcome, result_body=json.dumps(document))


def started(
    candidate: Candidate,
    *,
    traceparent: str | None = f"00-{TRACE_ID}-0123456789abcdef-01",
) -> sf.events.Started:
    return sf.events.Started(
        id="event-1",
        run_id="internal-stream-topic",
        sequence=1,
        timestamp=datetime.now(UTC),
        source="fixture",
        traceparent=traceparent,
        url4=candidate.url4,
    )


def load_benchmark(benchmark: str, limit: int | None) -> _BenchmarkResource:
    assert (benchmark, limit) == ("draco", 1)
    return RESOURCE


async def load_benchmark_async(
    benchmark: str,
    limit: int | None,
) -> _BenchmarkResource:
    return load_benchmark(benchmark, limit)


def load_catalog() -> Catalog:
    return Catalog()


async def load_catalog_async() -> Catalog:
    return Catalog()


def load_details(model: str) -> sf.ModelDetails:
    return _decode_model_details(_model_details(model), expected_model=model)


async def load_details_async(model: str) -> sf.ModelDetails:
    return load_details(model)


def candidate() -> sf.Model:
    return sf.Model(
        "provider/opus",
        prompt="private answer instruction",
        params={"max_tokens": 64},
    )


__all__ = [
    "AsyncFailingTransport",
    "BENCHMARK_URL4",
    "candidate",
    "FailingTransport",
    "load_benchmark",
    "load_benchmark_async",
    "load_catalog",
    "load_catalog_async",
    "load_details",
    "load_details_async",
    "PartialTransport",
    "RESOURCE",
    "started",
    "TRACE_ID",
]
