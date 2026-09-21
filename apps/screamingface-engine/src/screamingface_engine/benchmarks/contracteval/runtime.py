"""ContractEval's exam declaration — the serving spine runs the kitchen (OME-1236).

If `definition.py` writes the recipe, this module now only declares what makes this
exam different: how its booklet rows look, how a reply is graded against the private
gold spans, and which reducer rolls the verdicts into the paper's confusion-matrix F1.
The routes, memoized preflight, case serving and aggregate wiring live in
`spine/serving.py` — one kitchen for every hand-built deterministic board.

INVARIANT: everything here is deterministic and spends no tokens. The model calls live
in the expression, not in these handlers — which is the whole reason this board's
grading is free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contracteval import aggregate as reducing
from screamingface_engine.benchmarks.contracteval.case_evaluation import (
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.contracteval.definition import (
    BENCHMARK_ID,
    CASE_COUNT,
    REVISION,
)
from screamingface_engine.benchmarks.contracteval.grading import is_abstention, jaccard, verdict
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.evaluation import (
    candidate_answer,
    compact_json,
    positive_case_id,
)
from screamingface_engine.benchmarks.spine.serving import (
    ServedBoard,
    board_preflight,
    candidate_record,
    install_board,
    serve_cases,
)
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path) -> None:
    """Register every route this board's expression references."""

    install_board(node, root, BOARD)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the baked assets cannot serve this exam."""

    board_preflight(root, case_ids, label="ContractEval", load_answer=reducing.load_answer)


def _cases(root: Path):
    """The public booklet, served by the spine with this board's declaration."""

    return serve_cases(root, BOARD)


def _build_rows(root: Path, rows: list[Any]) -> list[dict[str, Any]]:
    """Project the baked rows into the sealed public booklet — never the gold spans.

    WHY the whole instruction text is baked rather than assembled here: prompt bytes
    are exam identity on a judge-free board, and an expression that composed them
    would put that identity outside the revision hash.
    """

    return [
        {"id": int(row["id"]), "case_id": str(int(row["id"])), "input": row["input"]}
        for row in rows
    ]


def _check(root: Path):
    """The gate between "the Candidate said something" and "we have a verdict"."""

    def check(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
            answer = reducing.load_answer(root, case_id)
            if answer is None:
                raise ValueError(f"answer record for case {case_id} missing or invalid")
            reply = candidate_answer(request.context)
            gold_spans = [str(span) for span in answer["gold_spans"]]
        except (OSError, TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        record = candidate_record(
            reply,
            schema=CHECK_SCHEMA,
            case_id=case_id,
            verdict={
                # INVARIANT: all-or-nothing containment, computed once, here. The
                # aggregate never re-derives it — a second implementation is a second
                # chance to disagree.
                "correct": verdict(reply.text, gold_spans),
                "is_positive": bool(gold_spans),
                "abstained": is_abstention(reply.text),
                # WHY computed even for negative rows: the population rule (positive
                # rows only) is the AGGREGATE's to apply, so the record stays a plain
                # fact about this reply.
                "jaccard": jaccard(gold_spans, reply.text),
            },
            tail={"output": reply.text},
        )
        return compact_json(record)

    return check


BOARD = ServedBoard(
    benchmark_id=BENCHMARK_ID,
    label="ContractEval",
    revision=REVISION,
    declared_case_count=CASE_COUNT,
    # AIDEV-NOTE: late-bound through the module global so tests (and only tests)
    # can monkeypatch `runtime.preflight` — a direct reference would freeze it.
    preflight=lambda root, case_ids: preflight(root, case_ids),
    build_rows=_build_rows,
    check=_check,
    bind_case_evaluation=bind_case_evaluation,
    reduce=reducing.aggregate,
)

__all__ = ["BOARD", "install", "preflight"]
