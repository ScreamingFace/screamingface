"""Binding a start to its Run's Candidate (E5 P1 spec R2, D12): `GET /?q=` with `X-SF-Run`
and `X-SF-Run-Candidate` binds before anything is scheduled and confirms after.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import NamedTuple

from fastapi import Request

from screamingface_engine.auth import ProblemException
from screamingface_engine.rest.runs_boundary import (
    CANDIDATE_ALREADY_STARTED,
    CANDIDATE_HEADER,
    RUN_CANCELED,
    RUN_HEADER,
    RUN_NOT_FOUND,
    private_failure,
    problem,
    request_caller,
    run_not_found,
    stop_candidate,
)
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import (
    MAX_CANDIDATES,
)
from screamingface_engine.runs.registry import (
    CandidateAlreadyStarted,
    RunCanceled,
    RunNotFound,
    RunRegistry,
    UnknownCandidate,
)
from screamingface_engine.world.wire import MALFORMED_HEADER

_logger = logging.getLogger(__name__)

# WHY a bound on the start's two registry writes: a hung database must not hold every bound
# start; past it the start runs unbound and its outcome still settles the Candidate (spec §8).
_START_WRITE_TIMEOUT_S = 5.0


# How a refused bind answers: (status, title, code, detail).
_REFUSALS: dict[type[Exception], tuple[int, str, str, str]] = {
    RunNotFound: (404, "Not Found", RUN_NOT_FOUND, "no such run"),
    UnknownCandidate: (400, "Bad Request", MALFORMED_HEADER, "the run has no such Candidate"),
    RunCanceled: (409, "Conflict", RUN_CANCELED, "the run was canceled"),
    CandidateAlreadyStarted: (
        409,
        "Conflict",
        CANDIDATE_ALREADY_STARTED,
        "the Candidate or the topic is already bound to another start",
    ),
}


def _start_binding(request: Request) -> tuple[RunRegistry, str, int] | None:
    """(registry, run id, Candidate index) for a start that names a Run, else None."""
    runs, candidates = (
        request.headers.getlist(RUN_HEADER),
        request.headers.getlist(CANDIDATE_HEADER),
    )
    registry = getattr(request.app.state, "run_registry", None)
    if registry is None or (not runs and not candidates):
        # Runs off: the start runs unbound, as on an Engine without `/runs`.
        return None
    # WHY refuse a repeat: two field lines would bind whichever one `get` happened to return.
    run_id = runs[0] if len(runs) == 1 else None
    raw = candidates[0] if len(candidates) == 1 else None
    # WHY a length bound before `int`: a run of thousands of digits is costly to parse and
    # overflows the database's index column; no Run has more than `MAX_CANDIDATES`.
    if (
        run_id is None
        or raw is None
        or not raw.isascii()
        or not raw.isdigit()
        or len(raw) > len(str(MAX_CANDIDATES))
        or int(raw) >= MAX_CANDIDATES
    ):
        raise ProblemException(
            status=400,
            title="Bad Request",
            detail=f"{RUN_HEADER} and {CANDIDATE_HEADER}, the Candidate's zero-based index, "
            "come together",
            code=MALFORMED_HEADER,
        )
    return registry, run_id, int(raw)


class StartBinding(NamedTuple):
    """What a start learns from binding its topic."""

    # The step the start runs once scheduled: `confirm_scheduled`, or a no-op when unbound.
    on_scheduled: Callable[[], Awaitable[None]]
    # When the bind began, for a bound start: its run's deadline counts from here (D12).
    bound_at: datetime | None = None


async def bind_start(request: Request, topic: str) -> StartBinding:
    """Bind the start's topic to its Run's Candidate, before anything is scheduled.

    Returns the step the start runs once scheduled and, for a bound start, when the bind began.
    WHY the bind moment: a cancel can tombstone the topic only after the bind, so a deadline
    counted from it ends before the tombstone expires (E5 P1 spec D12). A start without
    `X-SF-Run` is unchanged. A bind that fails on the database is logged and the start proceeds
    unbound (spec §8): history never blocks an evaluation.
    """
    binding = _start_binding(request)
    if binding is None:
        return StartBinding(_unbound)
    registry, run_id, candidate = binding
    owner = request_caller(request)
    if owner is None or not RUN_ID_PATTERN.fullmatch(run_id):
        raise run_not_found(run_id)
    bound_at = datetime.now(UTC)
    try:
        async with asyncio.timeout(_START_WRITE_TIMEOUT_S):
            await registry.bind(owner, run_id, candidate, topic)
    except tuple(_REFUSALS) as exc:
        status, title, code, detail = _REFUSALS[type(exc)]
        # Private: whether a Run is canceled or not yours depends on who asks.
        raise problem(status=status, title=title, detail=detail, code=code) from exc
    except Exception:
        _logger.warning("run bind failed topic=%s; starting unbound", topic, exc_info=True)
        # WHY keep `bound_at`: the bind may have committed with its acknowledgement lost, so a
        # cancel can still tombstone the topic (D12). An earlier deadline only shortens the run.
        return StartBinding(_unbound, bound_at)
    return StartBinding(functools.partial(confirm_scheduled, request, topic), bound_at)


def canceled_before_schedule() -> ProblemException:
    """A start whose topic a cancel stopped before it was scheduled: nothing runs (D12)."""
    # Private: whether a Run is canceled depends on who asks.
    return problem(
        status=409,
        title="Conflict",
        detail="the run was canceled before this Candidate started",
        code=RUN_CANCELED,
    )


async def _unbound() -> None:
    """An unbound start has nothing to confirm."""


async def confirm_scheduled(request: Request, topic: str) -> None:
    """Move the bound Candidate to `scheduled`. A cancel that won between the bind and here
    stopped the Candidate, so the start stops what it just scheduled and answers 409."""
    registry: RunRegistry = request.app.state.run_registry
    try:
        async with asyncio.timeout(_START_WRITE_TIMEOUT_S):
            stands = await registry.mark_scheduled(topic)
    except Exception:
        # WHY carry on: the run is scheduled; its outcome still settles it (R4).
        _logger.warning("run mark_scheduled failed topic=%s", topic, exc_info=True)
        return
    if not stands:
        try:
            await stop_candidate(request, topic)
            await registry.stop_done(topic)
        except BaseException as exc:
            raise private_failure(exc) from exc
        # Private: whether a Run is canceled depends on who asks.
        raise problem(
            status=409,
            title="Conflict",
            detail="the run was canceled while this Candidate started",
            code=RUN_CANCELED,
        )


__all__ = [
    "StartBinding",
    "bind_start",
    "canceled_before_schedule",
    "confirm_scheduled",
]
