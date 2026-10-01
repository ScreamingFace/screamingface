"""Write report.json one Candidate at a time."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime

from screamingface._report_primitives import Usage
from screamingface.discovery import BenchmarkInfo
from screamingface.report import (
    CandidateResult,
    _combined_usage,
    _require_report_benchmark,
    _require_report_candidate,
    _require_report_candidate_names,
    _timestamp_text,
)

_ORDER_MESSAGE = "Report candidates must match candidate_names in order"


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_report_json(
    write: Callable[[str], object],
    *,
    benchmark: BenchmarkInfo,
    case_count: int,
    started_at: datetime,
    completed_at: datetime,
    candidate_names: Sequence[str],
    candidates: Iterable[CandidateResult],
) -> None:
    """Emit the report.v1 document as text fragments, holding one Candidate dict at a time.

    FEATURE (OME-1448): the fragments concatenate to exactly
    `json.dumps(report.to_dict(), ensure_ascii=False, separators=(",", ":"))`.
    """
    benchmark_dict = _require_report_benchmark(benchmark, case_count)
    names = tuple(candidate_names)
    _require_report_candidate_names(names)
    # WHY text fragments, not bytes: `to_json()` returns a str even for text holding lone
    # surrogates, and a UTF-8 encode would raise on them. The caller picks the encoding.
    write(
        '{"schema":'
        + _encode("screamingface.report.v1")
        + ',"started_at":'
        + _encode(_timestamp_text(started_at))
        + ',"completed_at":'
        + _encode(_timestamp_text(completed_at))
        + ',"benchmark":'
        + _encode(benchmark_dict)
        + ',"candidates":['
    )
    usages = _write_candidates(write, benchmark, case_count, names, candidates)
    write('],"usage":' + _encode(_combined_usage(usages).to_dict()) + "}")


def _write_candidates(
    write: Callable[[str], object],
    benchmark: BenchmarkInfo,
    case_count: int,
    names: tuple[str, ...],
    candidates: Iterable[CandidateResult],
) -> tuple[Usage, ...]:
    usages: list[Usage] = []
    for index, candidate in enumerate(candidates):
        _require_report_candidate(benchmark, case_count, candidate)
        if index >= len(names) or candidate.name != names[index]:
            raise ValueError(_ORDER_MESSAGE)
        # INVARIANT: only this Candidate's dict is alive; its `usage` is all that outlives it.
        write(("," if index else "") + _encode(candidate.to_dict()))
        usages.append(candidate.usage)
    if len(usages) != len(names):
        raise ValueError(_ORDER_MESSAGE)
    return tuple(usages)


__all__: list[str] = []
