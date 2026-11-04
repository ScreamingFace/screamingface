"""Serve and validate public cases before native URL4 selection and execution."""

import json
from collections.abc import Awaitable, Callable

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.board_store import BoardStore
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.picture_admission import (
    refuse_blind_candidate,
    refuse_blind_models,
)
from screamingface_engine.benchmarks.selection import CaseSelection
from screamingface_engine.process_memory import log_process_memory
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def install_cases(node: Url4Node, route: str, provider: Callable[[], str]) -> None:
    """Register the existing cases route as a validated collection producer."""
    if route not in node.processor_routes():
        node.endpoint(route)(cases_handler(provider, node=node))


def cases_handler(
    provider: Callable[[], str], *, node: Url4Node | None = None
) -> Callable[[Request], str | Awaitable[str]]:
    def cases(request: Request) -> str | Awaitable[str]:
        raw = provider()
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError("invalid selection")
            selection: CaseSelection = CaseSelection.parse(request.intent, available=len(rows))
            served: str = raw if selection.is_prefix else _selected_rows(rows, selection)
            if any(not isinstance(row, dict) for row in rows[: selection.count]):
                raise ValueError("case rows must be objects")
        except (TypeError, ValueError) as exc:
            raise ResolutionError(
                "Invalid benchmark case selection", code="benchmark_contract_error", permanent=True
            ) from exc
        # FEATURE (memory diagnostics, OME-1314): the point a raw-provider Benchmark's Cases pass
        # through, loaded and parsed — what the run holds here is the Cases' cost (Imported
        # Boards log the same line in `board_cases_handler`). Only the COUNT, never a row.
        log_process_memory("cases_loaded", cases=len(rows))
        # FEATURE (OME-1548): the Cases route runs once, before any Candidate call, so it is the
        # last point where a picture run can still refuse a blind model with nothing spent.
        # WHY every row, not rows[:count]: a picture anywhere makes it a picture Benchmark.
        # WHY a coroutine only here: the selection check above stays synchronous, so a bad
        # selection still raises at the call, before anything is awaited.
        if node is not None:
            return _admitted(node, [row for row in rows if isinstance(row, dict)], served)
        # INVARIANT: validation finishes before inference; URL4 owns slicing and indexing.
        return served

    return cases


def _selected_rows(rows: list[object], selection: CaseSelection) -> str:
    """Only the selected rows, in id order, each checked to sit at its own position (OME-1739).

    WHY a count keeps the whole booklet: url4's ``slice=(0, N)`` cuts it, and serving the
    bytes unchanged keeps every ``limit=`` run's Cases step byte-identical.
    """

    selected: list[object] = [rows[case_id - 1] for case_id in selection.case_ids]
    for row, case_id in zip(selected, selection.case_ids, strict=True):
        if not isinstance(row, dict) or row.get("id") != case_id:
            raise ValueError(f"Case {case_id} is not stored at its position")
    return json.dumps(selected, ensure_ascii=False, separators=(",", ":"))


async def _admitted(node: Url4Node, rows: list[dict[str, object]], raw: str) -> str:
    """Serve ``raw`` once the run's Candidate may see this Benchmark's pictures."""
    await refuse_blind_models(node, rows)
    return raw


def install_board_cases(
    node: Url4Node,
    route: str,
    open_board: Callable[[], BoardStore],
    *,
    serve: Callable[[str], str] | None = None,
) -> None:
    """Register an Imported Board's Cases route, read through the board's index (OME-1790)."""
    if route not in node.processor_routes():
        node.endpoint(route)(board_cases_handler(open_board, node=node, serve=serve))


def board_cases_handler(
    open_board: Callable[[], BoardStore],
    *,
    node: Url4Node | None = None,
    serve: Callable[[str], str] | None = None,
) -> Callable[[Request], str | Awaitable[str]]:
    """The selection-aware Cases route: only the selected rows are read and served.

    FEATURE (OME-1790): a 2-Case run of a 330 MB board reads 2 rows. The url4 ``slice=(0, N)``
    stays in the protocol, so the recipe bytes do not move; over N served rows it is a no-op.
    ``serve`` (the candidate-input envelope, OME-1527) runs over those rows only.
    """

    @observe_phase(ActivityKind.CASE_LOADING)
    def load(intent: str) -> tuple[str, bool]:
        try:
            board: BoardStore = open_board()
            selection: CaseSelection = CaseSelection.parse(intent, available=board.case_count())
            # OME-1739: an id list reads one row per id; 1..N stays one contiguous read.
            selected: str = (
                board.head(selection.count)
                if selection.is_prefix
                else board.rows(selection.case_ids)
            )
        except (TypeError, ValueError) as exc:
            raise ResolutionError(
                "Invalid benchmark case selection", code="benchmark_contract_error", permanent=True
            ) from exc
        # WHY outside the try: a broken Case's envelope names its id (OME-1271); it is not a
        # selection error and must not be reworded as one.
        served: str = selected if serve is None else serve(selected)
        # FEATURE (memory diagnostics, OME-1314): Imported Boards (FigQA among them) load their
        # Cases here, not through `cases_handler` — the same `cases_loaded` line, count only.
        log_process_memory("cases_loaded", cases=selection.count)
        return served, board.has_pictures()

    def cases(request: Request) -> str | Awaitable[str]:
        served, needs_pictures = load(request.intent)
        if node is not None:
            return _admitted_by_flag(node, needs_pictures, served)
        return served

    return cases


async def _admitted_by_flag(node: Url4Node, needs_pictures: bool, served: str) -> str:
    """Serve the selected rows once the Candidate may see this board's pictures."""
    await refuse_blind_candidate(node, needs_pictures=needs_pictures)
    return served
