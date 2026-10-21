"""Replay a published run from its pinned cache and judge it (OME-1613, spec §2–§5).

FEATURE: OME-1613 — `sf.evaluate(pinned_cache=…)` and `sf.evaluate(score_id=…)`. The published
score is found (`_scoreboard/replay_reads.py`), every argument is checked, the run replays from the
pinned cache through `evaluate_url4_*`, the result is judged by `_reproduction._classify`, and an
exact replay is recorded on the board.
STORY: as a researcher, I replay a published run at $0 and learn whether it reproduces.

INVARIANT: no path here starts a normal, paid run. Every refusal (ids, seed, recipe, a capture that
cannot be replayed) happens before a run is scheduled, and every run carries the pinned cache, so
the Engine answers each call from the copy or fails the case. A run the Engine does not acknowledge
as a replay is refused by `evaluate_url4_*` before it is judged.
"""

from __future__ import annotations

import copy
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from url4 import Url4Error, build

from screamingface import _reproduction
from screamingface._evaluation.model import _answer_seed_value
from screamingface._evaluation.url4 import evaluate_url4_async, evaluate_url4_sync
from screamingface._reproduction import Reproduction, _record_async, _record_sync
from screamingface._scoreboard.replay_reads import PublishedScore, pinned_cache_id
from screamingface.errors import ExecutionError, LeaderboardError, ReproductionError
from screamingface.report import CandidateResult, Report
from screamingface.warnings import EvaluationWarning

if TYPE_CHECKING:
    from screamingface.client import AsyncClient, Client
    from screamingface.events import Event

_UNKNOWN_PINNED_CACHE = "unknown_pinned_cache"
_ALL_MISSED_HINT = (
    "No case of this replay was found in the pinned cache, and there is no published score to "
    "compare with. Check that answer_seed and url4 are exactly those of the captured run: a run "
    "captured without a seed must be replayed without one."
)


@dataclass(frozen=True, slots=True)
class _Request:
    pinned_cache: str | None
    score_id: UUID | str | None
    url4: str | None
    answer_seed: int | None
    record: bool


@dataclass(frozen=True, slots=True)
class _Plan:
    """What the replay runs, decided before any run: the recipe, the seed and the copy."""

    url4: str
    answer_seed: int | None
    pinned_cache: str
    published: PublishedScore | None


def _request(
    pinned_cache: object,
    score_id: object,
    url4: object,
    answer_seed: object,
    record_reproduction: object,
) -> _Request:
    if pinned_cache is None and score_id is None:
        raise TypeError("a replay needs pinned_cache= or score_id=")
    if url4 is not None and not isinstance(url4, str):
        raise TypeError("url4 must be a string or None")
    if not isinstance(record_reproduction, bool):
        raise TypeError("record_reproduction must be a bool")
    if score_id is not None and not isinstance(score_id, UUID | str):
        raise TypeError("score_id must be a UUID or a score id string")
    return _Request(
        pinned_cache=None if pinned_cache is None else pinned_cache_id(pinned_cache),
        score_id=score_id,
        url4=url4,
        answer_seed=_answer_seed_value(answer_seed),
        record=record_reproduction,
    )


def _parsed(url4: str) -> object:
    try:
        return build(url4)
    except Url4Error as exc:
        raise ValueError(f"url4 does not parse: {exc}") from exc


def _same_recipe(passed: str, published: str) -> bool:
    """Compare two url4s as parsed recipes (spec §3, Q2), never as text."""

    return _parsed(passed) == build(published)


def _not_reproducible(published: PublishedScore) -> Reproduction | None:
    """A published score that cannot name everything a replay needs starts no run (Q14)."""

    if published.capture_status == "partial":
        return Reproduction(outcome="not_reproducible", reason="partial")
    if (
        published.capture_status is None
        or published.pinned_cache is None
        or published.benchmark_revision is None
    ):
        return Reproduction(outcome="not_reproducible", reason="unknown")
    return None


def _plan(request: _Request, published: PublishedScore | None) -> _Plan:
    """Every check before any run (spec §3, §4a). Raises on anything that would miss the copy."""

    if published is None:
        # S4: no published score. Only the caller's url4 and seed can name the run.
        if request.url4 is None or request.pinned_cache is None:
            raise ValueError(
                "No public score uses this pinned cache. To replay a capture that was never "
                "submitted, pass url4= (and answer_seed= if the run had one); to replay a "
                "private score you submitted, pass score_id=."
            )
        _parsed(request.url4)
        return _Plan(request.url4.strip(), request.answer_seed, request.pinned_cache, None)
    if request.pinned_cache is not None and published.pinned_cache != request.pinned_cache:
        raise ValueError("the score's pinned cache is not the pinned_cache passed")
    refused = _not_reproducible(published)
    if refused is not None:
        raise ReproductionError(
            f"Score {published.score_id} cannot be replayed: its capture is {refused.reason}",
            reproduction=refused,
            code="not_reproducible",
        )
    # INVARIANT (§4a rows 3 and 5): `is not None`, never truthiness. 0 is a seed, and a seed
    # passed for a run captured without one would miss every call.
    if request.answer_seed is not None and request.answer_seed != published.answer_seed:
        raise ValueError(
            f"answer_seed={request.answer_seed} differs from the published run's "
            f"({published.answer_seed}); a replay must use the captured seed"
        )
    if request.url4 is not None and not _same_recipe(request.url4, published.url4):
        raise ValueError("replay needs the exact recipe: url4 is not the published url4")
    assert published.pinned_cache is not None  # checked by `_not_reproducible`
    return _Plan(published.url4, published.answer_seed, published.pinned_cache, published)


def _replay_unsupported(exc: ExecutionError) -> ReproductionError:
    if exc.hint is not None:
        # The stop of an unacknowledged replay may have failed; the run may still go on.
        warnings.warn(exc.user_message, EvaluationWarning, stacklevel=4)
    return ReproductionError(
        "SF Engine did not replay the run from the pinned cache",
        reproduction=Reproduction(outcome="failed", reason="replay_unsupported"),
        code="replay_unsupported",
    )


def _every_case_missed(result: CandidateResult) -> bool:
    return bool(result.cases) and all(
        any(failure.code == "frozen_copy_miss" for failure in case.failures)
        for case in result.cases
    )


def _with_reproduction(report: Report, reproduction: Reproduction | None) -> Report:
    (result,) = report.candidates
    judged = copy.copy(result)
    object.__setattr__(judged, "reproduction", reproduction)
    return Report(benchmark=report.benchmark, case_count=report.case_count, candidates=(judged,))


def _unjudged(report: Report) -> Report:
    # S4: no published score, so no verdict. Q11: when every case missed the copy, the likely
    # cause is a seed or recipe that is not the captured run's; say so once.
    if _every_case_missed(report.candidates[0]):
        warnings.warn(_ALL_MISSED_HINT, EvaluationWarning, stacklevel=4)
    return _with_reproduction(report, None)


def _missing_copy(error: LeaderboardError) -> bool:
    return error.code == _UNKNOWN_PINNED_CACHE


def _found_sync(client: Client, request: _Request) -> PublishedScore | None:
    if request.score_id is not None:
        return client.leaderboards._published_score(request.score_id)
    assert request.pinned_cache is not None
    try:
        return client.leaderboards._published_by_pinned_cache(request.pinned_cache)
    except LeaderboardError as exc:
        if not _missing_copy(exc):
            raise
        return None


async def _found_async(client: AsyncClient, request: _Request) -> PublishedScore | None:
    if request.score_id is not None:
        return await client.leaderboards._published_score(request.score_id)
    assert request.pinned_cache is not None
    try:
        return await client.leaderboards._published_by_pinned_cache(request.pinned_cache)
    except LeaderboardError as exc:
        if not _missing_copy(exc):
            raise
        return None


def _judged(report: Report, published: PublishedScore) -> tuple[CandidateResult, Reproduction]:
    result = report.candidates[0]
    # Looked up on the module so the verdict has one seam a test can replace.
    outcome, reason, missed = _reproduction._classify(published, result)
    return result, Reproduction(outcome=outcome, reason=reason, missed_cases=missed)


def _run_sync(
    client: Client,
    plan: _Plan,
    record: bool,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
) -> Report:
    try:
        report = evaluate_url4_sync(
            client._transport,
            plan.url4,
            on_event,
            progress,
            answer_seed=plan.answer_seed,
            # The Engine refuses X-Capture with X-Replay-Frozen-Copy (S6).
            capture=False,
            replay_frozen_copy=plan.pinned_cache,
        )
    except ExecutionError as exc:
        if exc.code != "replay_unsupported":
            raise
        raise _replay_unsupported(exc) from exc
    if plan.published is None:
        return _unjudged(report)
    result, reproduction = _judged(report, plan.published)
    if record and reproduction.outcome == "exact":
        reproduction = _record_sync(client, plan.published, result, reproduction)
    return _with_reproduction(report, reproduction)


async def _run_async(
    client: AsyncClient,
    plan: _Plan,
    record: bool,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
) -> Report:
    try:
        report = await evaluate_url4_async(
            client._transport,
            plan.url4,
            on_event,
            progress,
            answer_seed=plan.answer_seed,
            capture=False,
            replay_frozen_copy=plan.pinned_cache,
        )
    except ExecutionError as exc:
        if exc.code != "replay_unsupported":
            raise
        raise _replay_unsupported(exc) from exc
    if plan.published is None:
        return _unjudged(report)
    result, reproduction = _judged(report, plan.published)
    if record and reproduction.outcome == "exact":
        reproduction = await _record_async(client, plan.published, result, reproduction)
    return _with_reproduction(report, reproduction)


def _published_request(published: PublishedScore, record: bool) -> _Request:
    return _Request(
        pinned_cache=None, score_id=published.score_id, url4=None, answer_seed=None, record=record
    )


def replay_published_sync(
    client: Client,
    published: PublishedScore,
    *,
    record: bool,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = False,
) -> Report:
    """Replay a score that is already found; `replay_sync` finds it first."""

    return _run_sync(
        client, _plan(_published_request(published, record), published), record, on_event, progress
    )


async def replay_published_async(
    client: AsyncClient,
    published: PublishedScore,
    *,
    record: bool,
    on_event: Callable[[Event], None | Awaitable[None]] | None = None,
    progress: bool | None = False,
) -> Report:
    return await _run_async(
        client, _plan(_published_request(published, record), published), record, on_event, progress
    )


def replay_sync(
    client: Client,
    *,
    pinned_cache: str | None,
    score_id: UUID | str | None,
    url4: str | None,
    answer_seed: int | None,
    record_reproduction: bool,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
) -> Report:
    request = _request(pinned_cache, score_id, url4, answer_seed, record_reproduction)
    plan = _plan(request, _found_sync(client, request))
    return _run_sync(client, plan, request.record, on_event, progress)


async def replay_async(
    client: AsyncClient,
    *,
    pinned_cache: str | None,
    score_id: UUID | str | None,
    url4: str | None,
    answer_seed: int | None,
    record_reproduction: bool,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
) -> Report:
    request = _request(pinned_cache, score_id, url4, answer_seed, record_reproduction)
    plan = _plan(request, await _found_async(client, request))
    return await _run_async(client, plan, request.record, on_event, progress)


__all__ = ["replay_async", "replay_published_async", "replay_published_sync", "replay_sync"]
