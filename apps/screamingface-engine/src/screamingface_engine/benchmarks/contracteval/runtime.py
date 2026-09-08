"""Install ContractEval's private assets and deterministic functions into one Runner world.

If `definition.py` writes the recipe, this module is the kitchen: a handler behind each route
so the recipe can resolve.

    /cases           → the public booklet (contract + question, never which sentences answer it)
    /check           → the Candidate replied: verdict against the private gold spans
    /case-evaluation → collect the checked attempt into the per-Case artifact
    /aggregate       → reduce every Case into the paper's confusion-matrix F1

INVARIANT: everything here is deterministic and spends no tokens. The model calls live in the
expression, not in these handlers — which is the whole reason this board's grading is free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contracteval import aggregate as reducing
from screamingface_engine.benchmarks.contracteval.case_evaluation import (
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.contracteval.definition import (
    AGGREGATE_ROUTE,
    BENCHMARK_ID,
    CASE_EVALUATION_ROUTE,
    CASES_ROUTE,
    CHECK_ROUTE,
    REVISION,
)
from screamingface_engine.benchmarks.contracteval.grading import is_abstention, jaccard, verdict
from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    attempt_records_endpoint,
    candidate_answer,
    compact_json,
    positive_case_id,
)
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path) -> None:
    """Register every route this board's expression references."""

    if CASES_ROUTE not in getattr(node, "_data", {}):
        node.data(CASES_ROUTE, _cases(root), media_type="application/json")
    installed = frozenset(node.processor_routes())
    endpoints = (
        (CHECK_ROUTE, _check(root)),
        (
            CASE_EVALUATION_ROUTE,
            attempt_records_endpoint(
                label="ContractEval Case evaluation",
                item_name="Attempt",
                bind=bind_case_evaluation,
                error_context_head=300,
            ),
        ),
        (
            AGGREGATE_ROUTE,
            aggregate_endpoint(
                label="ContractEval",
                available_case_count=_case_count(root),
                aggregate=_aggregate(root),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def preflight(root: Path, case_ids: tuple[int, ...]) -> None:
    """Fail before the FIRST paid call when the baked assets cannot serve this exam."""

    problems: list[str] = []
    if not (root / "cases.json").is_file():
        problems.append(f"cases.json missing under {root}")
    for case_id in case_ids:
        if reducing.load_answer(root, case_id) is None:
            problems.append(f"answer record for case {case_id} missing or invalid")
    if problems:
        raise _unavailable("ContractEval assets failed preflight: " + "; ".join(problems[:8]))


def _cases(root: Path):
    def cases() -> str:
        """The public booklet.

        WHY the whole instruction text is baked rather than assembled here: prompt bytes are
        exam identity on a judge-free board, and an expression that composed them would put that
        identity outside the revision hash.
        """

        rows = json.loads(_read(root / "cases.json", "ContractEval cases"))
        return json.dumps(
            [
                {"id": int(row["id"]), "case_id": str(int(row["id"])), "input": row["input"]}
                for row in rows
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return cases


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
        record: dict[str, Any] = {
            "schema": CHECK_SCHEMA,
            "case_id": case_id,
            "attempt": 1,
            # INVARIANT: all-or-nothing containment, computed once, here. The aggregate never
            # re-derives it — a second implementation is a second chance to disagree.
            "correct": verdict(reply.text, gold_spans),
            "is_positive": bool(gold_spans),
            "abstained": is_abstention(reply.text),
            # WHY computed even for negative rows: the population rule (positive rows only) is
            # the AGGREGATE's to apply, so the record stays a plain fact about this reply.
            "jaccard": jaccard(gold_spans, reply.text),
            "status": reply.status,
            "refusal": reply.refusal,
            "finish_reason": reply.finish_reason,
            "output": reply.text,
            "execution": (
                None if reply.execution is None else reply.execution.model_dump(by_alias=True)
            ),
            **(
                {}
                if reply.operations is None
                else {
                    "operations": [
                        operation.model_dump(by_alias=True) for operation in reply.operations
                    ]
                }
            ),
        }
        return compact_json(record)

    return check


def _aggregate(root: Path):
    def aggregate_handler(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        case_ids = tuple(range(1, selected_case_count + 1))
        return reducing.aggregate(
            case_evaluations,
            root,
            benchmark_id=BENCHMARK_ID,
            benchmark_revision=REVISION,
            case_ids=case_ids,
        )

    return aggregate_handler


def _case_count(root: Path) -> int:
    try:
        return len(json.loads((root / "cases.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        # The board's declared count stands in when assets are absent at install time; preflight
        # is what refuses a run whose assets cannot serve it.
        from screamingface_engine.benchmarks.contracteval.definition import CASE_COUNT

        return CASE_COUNT


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"{label} unavailable: {exc}") from exc


__all__ = ["install", "preflight"]
