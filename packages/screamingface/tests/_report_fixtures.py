"""Small Report builders shared by the report writer and streaming export tests."""

from __future__ import annotations

import json
import os
import tracemalloc
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

import screamingface as sf
from screamingface._evaluation.model import _compiled_operation

CASE_COUNT = 2


def benchmark() -> sf.BenchmarkInfo:
    return sf.BenchmarkInfo(id="draco", revision="fixture-revision", case_count=100)


def candidate(
    name: str,
    *,
    text: str = "Question",
    usage: sf.Usage | None = None,
    start_minute: int = 0,
    case_count: int = CASE_COUNT,
    benchmark_info: sf.BenchmarkInfo | None = None,
) -> sf.CandidateResult:
    cases = tuple(
        sf.CaseResult(
            case_id=case_id,
            input=f"{text} {case_id}",
            output=f"Answer {case_id}",
            finish_reason="stop",
            grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        )
        for case_id in range(1, case_count + 1)
    )
    started = datetime(2026, 7, 25, 16, 0, tzinfo=UTC) + timedelta(minutes=start_minute)
    return sf.CandidateResult(
        benchmark=benchmark_info or benchmark(),
        run_id=f"run_{name}",
        started_at=started,
        completed_at=started + timedelta(seconds=1, milliseconds=200),
        name=name,
        kind="model",
        url4=f"(@)!'{name}'",
        models=(f"provider/{name}",),
        operations=(
            _compiled_operation(
                id=f"op_{name}", kind="model", label=f"{name} answer", depends_on=()
            ),
        ),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=usage or sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
    )


def report(*candidates: sf.CandidateResult) -> sf.Report:
    return sf.Report(benchmark=benchmark(), case_count=CASE_COUNT, candidates=candidates)


def oracle(value: sf.Report) -> str:
    """The document `Report.to_json()` produced before the streaming writer existed."""
    return json.dumps(value.to_dict(), ensure_ascii=False, separators=(",", ":"))


def large_candidates(count: int) -> tuple[sf.CandidateResult, ...]:
    """Candidates whose escaped JSON is about 1 MB each, so string copies show up in a peak."""
    text = 'He said "hi"\\n and left. ' * 20_000
    return tuple(candidate(f"large-{index}", text=text) for index in range(count))


def peak_bytes(action: Callable[[], object]) -> int:
    """Extra memory `action` allocates at its peak, leaving any outer tracing session running."""
    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        baseline = tracemalloc.get_traced_memory()[0]
        action()
        return tracemalloc.get_traced_memory()[1] - baseline
    finally:
        if not already_tracing:
            tracemalloc.stop()


class _TrackedDict(dict[str, object]):
    """A dict that supports weak references, which a plain dict does not."""

    __slots__ = ("__weakref__",)


def track_live_candidate_dicts(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record, at each `CandidateResult.to_dict` call, how many earlier results are still alive."""
    original = sf.CandidateResult.to_dict
    references: list[weakref.ref[_TrackedDict]] = []
    live_before_each_call: list[int] = []

    def tracked(self: sf.CandidateResult) -> dict[str, object]:
        live_before_each_call.append(sum(ref() is not None for ref in references))
        result = _TrackedDict(original(self))
        references.append(weakref.ref(result))
        return result

    monkeypatch.setattr(sf.CandidateResult, "to_dict", tracked)
    return live_before_each_call


@contextmanager
def umask(value: int) -> Iterator[int]:
    """Set a known process umask for one test, then restore it (test-only: never in src)."""
    previous = os.umask(value)
    try:
        yield value
    finally:
        os.umask(previous)


__all__: list[str] = []
