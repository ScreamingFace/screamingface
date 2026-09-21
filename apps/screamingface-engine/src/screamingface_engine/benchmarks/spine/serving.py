"""The serving spine — one kitchen shared by every hand-built deterministic board.

Think of a board as an exam: the DECLARATION says what makes this exam different
(its dataset, prompt bytes, grading rules, scorer), and this module is the exam
hall that serves any declaration — builds the routes, refuses a broken bundle
before money moves, hands out the booklet, and rolls graded papers into a score.

Execution order, per run:

    1. `board_routes` / `compute_board_revision` — `definition.py` fingerprints the
       exam and derives the addresses its expression references.
    2. `install_board` — registers the four routes behind one `ServedBoard`
       declaration; a registered board is structurally served, so no hand-wired
       slot (the PR #865 "preflight defined, invoked from nowhere" class) exists.
    3. `serve_cases` — the public booklet. Runs `board_preflight` at the last
       moment before money moves and memoizes ONLY a success.
    4. the board's own `check` — exam-specific, stays in the board; it assembles
       its record through `candidate_record` so the envelope stays byte-stable.
    5. `board_aggregate` — forwards graded Cases plus exam identity to the
       board's reducer.

INVARIANT: everything here is deterministic and spends no tokens. The model calls
live in the expression, not in these handlers.

FEATURE (OME-1236): a new deterministic board declares only its exam — this module
owns the ~600 lines of plumbing each board used to re-type by hand.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.evaluation import (
    CandidateAnswer,
    CaseEvaluationBinder,
    aggregate_endpoint,
    attempt_records_endpoint,
    benchmark_unavailable,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

JsonObject = dict[str, Any]
AnswerLoader = Callable[[Path, int], Mapping[str, Any] | None]
RowBuilder = Callable[[Path, list[Any]], list[JsonObject]]
CheckFactory = Callable[[Path], Callable[[Request], str]]
ErrorFactory = Callable[[str], ResolutionError]
PreflightCheck = Callable[[Path, tuple[int, ...]], None]
# The per-board reducer signature every board's `aggregate.aggregate` already has:
# (case_evaluations, root, *, benchmark_id, benchmark_revision, case_ids) -> report.
BoardReducer = Callable[..., JsonObject]

# WHY 8: the preflight message travels in a public failure row — a bundle with
# thousands of broken cases must not ship a megabyte of diagnostics.
_PREFLIGHT_PROBLEM_CAP = 8


@dataclass(frozen=True, slots=True)
class BoardRoutes:
    """The four addresses a board's expression references, derived from exam identity."""

    prefix: str
    cases: str
    check: str
    case_evaluation: str
    aggregate: str


def board_routes(benchmark_id: str, revision: str) -> BoardRoutes:
    """Derive the route layout every hand-built board pins: /benchmarks/<id>/<revision>/…"""

    # INVARIANT: the layout is exam identity — recorded submissions resolve at these
    # exact addresses, so the shape is not free to drift.
    prefix = f"/benchmarks/{benchmark_id}/{revision}"
    return BoardRoutes(
        prefix=prefix,
        cases=f"{prefix}/cases",
        check=f"{prefix}/check",
        case_evaluation=f"{prefix}/case-evaluation",
        aggregate=f"{prefix}/aggregate",
    )


def compute_board_revision(*parts: str) -> str:
    """Fingerprint an exam's identity parts into the 16 hex characters its routes carry.

    WHY newline joining: it is what every existing board's baked revision used, and it
    keeps ("ab","c") distinct from ("a","bc").
    """

    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ServedBoard:
    """One deterministic board's declaration — everything its exam needs said once.

    The board writes what makes its exam different; the spine serves it. Fields:

    - `benchmark_id` / `revision`: exam identity; the route layout derives from them.
    - `label`: the human name endpoint failures speak ("ContractEval").
    - `declared_case_count`: stands in when assets are absent at install time.
    - `preflight`: refuses a broken bundle for the given case_ids by raising the
      board's failure class. Boards implement it with `board_preflight`; per-board
      deviations (contracteval says unavailable, medxpert says definition error)
      live in that call, not here. AIDEV-NOTE: pass a module-level function (or a
      closure over one) so tests can monkeypatch the board's `preflight` seam.
    - `build_rows`: turns the baked `cases.json` rows into the served public booklet.
      INVARIANT (sealed envelope): rows carry questions, never which answers grade them.
    - `check`: the board's own grading gate, given the bundle root. Exam-specific by
      design — the spine does not average over boards.
    - `bind_case_evaluation`: bundles checked attempts into the per-Case artifact.
    - `reduce`: the board's reducer (`aggregate.aggregate`), fed exam identity and the
      exact selected case_ids.
    """

    benchmark_id: str
    label: str
    revision: str
    declared_case_count: int
    preflight: PreflightCheck
    build_rows: RowBuilder
    check: CheckFactory
    bind_case_evaluation: CaseEvaluationBinder
    reduce: BoardReducer

    @property
    def routes(self) -> BoardRoutes:
        return board_routes(self.benchmark_id, self.revision)


def install_board(node: Url4Node, root: Path, board: ServedBoard) -> None:
    """Register every route the board's expression references — the whole kitchen.

    WHY idempotent (skip already-installed routes): local mode installs one node for
    many runs, and a re-install must not fight the first.
    """

    routes = board.routes
    if routes.cases not in getattr(node, "_data", {}):
        node.data(routes.cases, serve_cases(root, board), media_type="application/json")
    installed = frozenset(node.processor_routes())
    endpoints = (
        (routes.check, board.check(root)),
        (
            routes.case_evaluation,
            attempt_records_endpoint(
                label=f"{board.label} Case evaluation",
                item_name="Attempt",
                bind=board.bind_case_evaluation,
                error_context_head=300,
            ),
        ),
        (
            routes.aggregate,
            aggregate_endpoint(
                label=board.label,
                available_case_count=board_case_count(root, declared=board.declared_case_count),
                aggregate=board_aggregate(root, board),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def board_preflight(
    root: Path,
    case_ids: tuple[int, ...],
    *,
    label: str,
    load_answer: AnswerLoader,
    error: ErrorFactory = benchmark_unavailable,
) -> None:
    """Fail before the FIRST paid call when the baked assets cannot serve this exam."""

    problems: list[str] = []
    if not (root / "cases.json").is_file():
        problems.append(f"cases.json missing under {root}")
    for case_id in case_ids:
        if load_answer(root, case_id) is None:
            problems.append(f"answer record for case {case_id} missing or invalid")
    if problems:
        raise error(
            f"{label} assets failed preflight: " + "; ".join(problems[:_PREFLIGHT_PROBLEM_CAP])
        )


def serve_cases(root: Path, board: ServedBoard) -> Callable[[], str]:
    """The public booklet — served only after the whole bundle passes preflight.

    WHY preflight HERE and not later (review, PR #865): handing out the booklet is the
    last moment before money moves. Serving inputs first and discovering a missing
    answer key at grading time means the run has already paid for inference it cannot
    score.

    WHY the memo holds a VERDICT and not the payload (review of PR #984): the booklet
    can run to hundreds of megabytes; caching bytes for the process lifetime is a
    permanent cost in local mode, where one process serves many runs. The expensive
    CHECK is paid once and the bytes are rebuilt per call.

    INVARIANT: only a SUCCESSFUL preflight is remembered, so a broken bundle re-fails
    on every call rather than being served from a cache primed before the failure.
    """

    preflighted = False

    def cases() -> str:
        nonlocal preflighted
        rows = json.loads(read_asset(root / "cases.json", f"{board.label} cases"))
        served = board.build_rows(root, rows)
        if not preflighted:
            board.preflight(root, tuple(int(row["id"]) for row in served))
            preflighted = True
        return json.dumps(served, ensure_ascii=False, separators=(",", ":"))

    return cases


def candidate_record(
    reply: CandidateAnswer,
    *,
    schema: str,
    case_id: int,
    verdict: Mapping[str, Any],
    tail: Mapping[str, Any],
) -> JsonObject:
    """Assemble the shared check-record envelope in its byte-stable field order.

    The board owns the middle (`verdict`: its graded facts) and the tail (`tail`: its
    output/reasoning text fields); the spine owns everything the shared candidate
    envelope carries. INVARIANT: field ORDER is part of the served bytes — migrated
    boards must produce byte-identical records through this helper:

        schema · case_id · attempt · <verdict…> · status · refusal · finish_reason
        · <tail…> · execution · [operations]
    """

    record: JsonObject = {
        "schema": schema,
        "case_id": case_id,
        "attempt": 1,
        **verdict,
        "status": reply.status,
        "refusal": reply.refusal,
        "finish_reason": reply.finish_reason,
        **tail,
        "execution": (
            None if reply.execution is None else reply.execution.model_dump(by_alias=True)
        ),
    }
    if reply.operations is not None:
        record["operations"] = [
            operation.model_dump(by_alias=True) for operation in reply.operations
        ]
    return record


def board_aggregate(root: Path, board: ServedBoard) -> Callable[[str, int], JsonObject]:
    """Forward graded Cases plus exam identity to the board's reducer.

    INVARIANT: case_ids are 1..selected — the reducer scores exactly the exam that was
    selected, and identity (id + revision) rides into the report.
    """

    def handler(case_evaluations: str, selected_case_count: int) -> JsonObject:
        case_ids: tuple[int, ...] = tuple(range(1, selected_case_count + 1))
        return board.reduce(
            case_evaluations,
            root,
            benchmark_id=board.benchmark_id,
            benchmark_revision=board.revision,
            case_ids=case_ids,
        )

    return handler


def board_case_count(root: Path, *, declared: int) -> int:
    """Count the baked booklet, or stand on the declared count when assets are absent.

    WHY the fallback: install happens on a resource-only control plane where assets may
    be absent; preflight — not this count — is what refuses a run it cannot serve.
    """

    try:
        return len(json.loads((root / "cases.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return declared


def read_asset(path: Path, label: str) -> str:
    """Read one baked asset, or fail bounded — never a raw OSError to a caller."""

    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise benchmark_unavailable(f"{label} unavailable: {exc}") from exc


__all__ = [
    "BoardRoutes",
    "ServedBoard",
    "board_aggregate",
    "board_case_count",
    "board_preflight",
    "board_routes",
    "candidate_record",
    "compute_board_revision",
    "install_board",
    "read_asset",
    "serve_cases",
]
