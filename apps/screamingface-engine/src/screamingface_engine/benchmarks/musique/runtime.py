"""MuSiQue-Ans's Benchmark declaration — the serving spine runs the kitchen (OME-1236).

This module only declares what makes this Benchmark different: how its public Cases look, how a
reply is read (the two committed lines), and which reducer turns the grades into the run's three
Named Scores. The routes, the memoized preflight, Case serving and aggregate wiring live in
`shared_grading/serving.py`.

INVARIANT: everything here is deterministic and spends no tokens. The model calls live in the
expression, not in these handlers — which is why this Benchmark's grading is free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.grading_endpoints import (
    CandidateAnswer,
    candidate_answer,
    compact_json,
    positive_case_id,
)
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.musique import aggregate as reducing
from screamingface_engine.benchmarks.musique.answering import ExtractedReply, extract_reply
from screamingface_engine.benchmarks.musique.case_grade import CHECK_SCHEMA, build_case_grade
from screamingface_engine.benchmarks.musique.definition import (
    BENCHMARK_ID,
    CASE_COUNT,
    REVISION,
)
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.shared_grading.serving import (
    ServedBenchmark,
    benchmark_preflight,
    candidate_record,
    install_benchmark,
)
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path) -> None:
    """Register every route this Benchmark's expression references."""

    install_benchmark(node, root, BENCHMARK)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the prepared assets cannot serve this Benchmark."""

    benchmark_preflight(root, case_ids, label="MuSiQue-Ans", load_answer=reducing.load_answer)


def _build_public_cases(root: Path, rows: list[Any]) -> list[dict[str, Any]]:
    """Project the prepared rows into the public Cases — the rendered input, never the gold.

    WHY the whole input is prepared rather than assembled here: prompt bytes are Benchmark
    identity on a judge-free Benchmark, and an expression that composed them would put that
    identity outside the Benchmark Revision.
    """

    return [
        {"id": int(row["id"]), "case_id": str(int(row["id"])), "input": row["input"]}
        for row in rows
    ]


def _check(root: Path):
    """The gate between "the Candidate said something" and "we know what it committed to"."""

    @observe_phase(ActivityKind.GRADING)
    def check(request: Request) -> str:
        try:
            case_id: int = positive_case_id(request.intent)
            report_case_grading(case_id, "started")
            reply: CandidateAnswer = candidate_answer(request.context)
        except (TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        # WHY the answer key is not read here: the record is a plain fact about the reply, and
        # the key is applied once, at grading. A missing key is the aggregate ladder's
        # `missing_answer_asset` (spec F7), which preflight already refuses before any spend.
        extracted: ExtractedReply = extract_reply(reply.text)
        record: dict[str, Any] = candidate_record(
            reply,
            schema=CHECK_SCHEMA,
            case_id=case_id,
            verdict={
                "answer": extracted.answer,
                "support": sorted(extracted.support),
                "answer_line": extracted.answer_line,
                "support_line": extracted.support_line,
            },
            tail={"output": reply.text},
        )
        return compact_json(record)

    return check


BENCHMARK = ServedBenchmark(
    benchmark_id=BENCHMARK_ID,
    label="MuSiQue-Ans",
    revision=REVISION,
    declared_case_count=CASE_COUNT,
    # AIDEV-NOTE: late-bound through the module global so `runtime.preflight` stays
    # replaceable in tests, as ContractEval's and MedXpert's are.
    preflight=lambda root, case_ids: preflight(root, case_ids),
    build_public_cases=_build_public_cases,
    check=_check,
    build_case_grade=build_case_grade,
    reduce=reducing.aggregate,
    scoring=reducing.scoring,
)

__all__ = ["BENCHMARK", "install", "preflight"]
