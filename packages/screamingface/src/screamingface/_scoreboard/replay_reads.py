"""Find the published score a pinned-cache replay is judged against (OME-1613, spec §2).

FEATURE: OME-1613 — `sf.evaluate(pinned_cache=…)` reads the public lookup by copy id
(`GET /v1/public/scores/by-pinned-cache/{id}`, OME-1596), which needs no login.
`sf.evaluate(score_id=…)` reads the public score (`GET /v1/public/scores/{id}`, OME-1650) and
falls back to the gated `GET /v1/scores/{id}` only when that answers 404: a private score, which
the gated read shows to its submitter alone.

WHY a separate `PublishedScore`: the lookup by copy id returns only the fields a replay needs,
not a whole score. Both reads are reduced to the same small value, so the replay has one shape
to check and judge against.

INVARIANT: only a 404 from the public read falls back to the gated read. Any other failure is the
board's answer and surfaces as it is: a 503 must not turn into a login prompt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import httpx

from screamingface._report_primitives import capture_status_value
from screamingface._scoreboard.leaderboards import (
    _async_json,
    _decode_score,
    _integer,
    _invalid,
    _mapping,
    _number,
    _optional_integer,
    _optional_text,
    _score_id,
    _sync_json,
    _text,
)
from screamingface.errors import LeaderboardError
from screamingface.leaderboard import LeaderboardScore, _case_digest, _positive_int, _score

_LOOKUP_PATH = "/v1/public/scores/by-pinned-cache"
_PUBLIC_SCORES_PATH = "/v1/public/scores"
_UNKNOWN_PINNED_CACHE = (
    "unknown_pinned_cache",
    "No public score uses pinned cache {id!r}. The cache id is unknown, the score is on a private "
    "board, or the capture was never submitted. A private score's submitter can replay it with "
    "score_id=; an unsubmitted capture replays with url4= (and answer_seed= if it had one).",
)


@dataclass(frozen=True, slots=True)
class PublishedScore:
    """The published numbers and recipe a replay is checked and judged against."""

    score_id: UUID
    pinned_cache: str | None
    capture_status: Literal["complete", "partial"] | None
    url4: str
    answer_seed: int | None
    score: float
    total_questions: int
    benchmark_id: str
    benchmark_revision: str | None
    case_digest: str | None


def published_from_score(score: LeaderboardScore) -> PublishedScore:
    return PublishedScore(
        score_id=score.id,
        pinned_cache=score.pinned_cache,
        capture_status=score.capture_status,
        url4=str(score.url4),
        answer_seed=score.answer_seed,
        score=score.score,
        total_questions=score.total_questions,
        benchmark_id=score.benchmark_id,
        benchmark_revision=score.benchmark_revision,
        case_digest=score.case_digest,
    )


def pinned_cache_id(value: object) -> str:
    """A frozen copy id is a canonical UUID string; anything else fails before any request."""

    if not isinstance(value, str):
        raise TypeError("pinned_cache must be a UUID string")
    try:
        canonical = str(UUID(value))
    except ValueError as exc:
        raise ValueError("pinned_cache must be a UUID") from exc
    if canonical != value:
        raise ValueError("pinned_cache must be a canonical lower-case UUID")
    return canonical


def _decode_lookup(payload: object, pinned_cache: str) -> PublishedScore:
    """The lookup, held to the same contract as a score read (`_decode_score`).

    INVARIANT: a malformed field is the board's contract error (`invalid_leaderboard`), never a bare
    ValueError that reads like the caller's mistake. The case digest is checked here too: a digest
    in another spelling would turn an exact replay into `cases_differ`.
    """
    root = _mapping(payload, "Pinned cache lookup")
    try:
        published = _lookup_fields(root, pinned_cache)
        _case_digest(published.case_digest, published.capture_status)
        # Review (#1519): the numbers a replay is judged against, as `LeaderboardScore` checks them.
        _score(published.score, "Pinned cache lookup score")
        _positive_int(published.total_questions, "Pinned cache lookup total_questions")
    except (TypeError, ValueError) as exc:
        _invalid(f"pinned cache lookup: {exc}", exc)
    return published


def _lookup_fields(root: Mapping[str, object], pinned_cache: str) -> PublishedScore:
    return PublishedScore(
        score_id=_score_id(_text(root.get("score_id"), "Pinned cache lookup score_id")),
        pinned_cache=pinned_cache,
        capture_status=capture_status_value(root.get("capture_status")),
        url4=_text(root.get("url4_expression"), "Pinned cache lookup url4_expression"),
        answer_seed=_optional_integer(root.get("answer_seed"), "Pinned cache lookup answer_seed"),
        score=_number(root.get("score"), "Pinned cache lookup score"),
        total_questions=_integer(
            root.get("total_questions"), "Pinned cache lookup total_questions"
        ),
        benchmark_id=_text(root.get("benchmark_id"), "Pinned cache lookup benchmark_id"),
        benchmark_revision=_optional_text(
            root.get("benchmark_revision"), "Pinned cache lookup benchmark_revision"
        ),
        case_digest=_optional_text(root.get("case_digest"), "Pinned cache lookup case_digest"),
    )


def _unknown_copy(pinned_cache: str) -> tuple[str, str]:
    code, message = _UNKNOWN_PINNED_CACHE
    return code, message.format(id=pinned_cache)


def _unknown_score(score_id: UUID) -> tuple[str, str]:
    return (
        "unknown_score",
        f"Score {str(score_id)!r} was not found, or it is private and this identity did not "
        "submit it",
    )


def _is_missing(error: LeaderboardError) -> bool:
    return error.status == 404


def published_by_pinned_cache_sync(
    request: Callable[..., httpx.Response], scoreboard_url: str, value: object
) -> PublishedScore:
    pinned_cache = pinned_cache_id(value)
    payload = _sync_json(
        request,
        scoreboard_url,
        "GET",
        f"{_LOOKUP_PATH}/{pinned_cache}",
        replay_safe=True,
        missing=_unknown_copy(pinned_cache),
    )
    return _decode_lookup(payload, pinned_cache)


async def published_by_pinned_cache_async(
    request: Callable[..., Awaitable[httpx.Response]], scoreboard_url: str, value: object
) -> PublishedScore:
    pinned_cache = pinned_cache_id(value)
    payload = await _async_json(
        request,
        scoreboard_url,
        "GET",
        f"{_LOOKUP_PATH}/{pinned_cache}",
        replay_safe=True,
        missing=_unknown_copy(pinned_cache),
    )
    return _decode_lookup(payload, pinned_cache)


def _decode_requested_score(payload: object, scoreboard_url: str, score_id: UUID) -> PublishedScore:
    score = _decode_score(payload, scoreboard_url)
    # INVARIANT: a response cannot redirect replay or recording to a different submission.
    if score.id != score_id:
        _invalid("Score response id does not match the requested score_id")
    return published_from_score(score)


def published_score_sync(
    request: Callable[..., httpx.Response], scoreboard_url: str, value: object
) -> PublishedScore:
    score_id = _score_id(value)
    missing = _unknown_score(score_id)
    try:
        payload = _sync_json(
            request,
            scoreboard_url,
            "GET",
            f"{_PUBLIC_SCORES_PATH}/{score_id}",
            replay_safe=True,
            missing=missing,
        )
    except LeaderboardError as exc:
        if not _is_missing(exc):
            raise
        payload = _sync_json(
            request,
            scoreboard_url,
            "GET",
            f"/v1/scores/{score_id}",
            replay_safe=True,
            missing=missing,
        )
    return _decode_requested_score(payload, scoreboard_url, score_id)


async def published_score_async(
    request: Callable[..., Awaitable[httpx.Response]], scoreboard_url: str, value: object
) -> PublishedScore:
    score_id = _score_id(value)
    missing = _unknown_score(score_id)
    try:
        payload = await _async_json(
            request,
            scoreboard_url,
            "GET",
            f"{_PUBLIC_SCORES_PATH}/{score_id}",
            replay_safe=True,
            missing=missing,
        )
    except LeaderboardError as exc:
        if not _is_missing(exc):
            raise
        payload = await _async_json(
            request,
            scoreboard_url,
            "GET",
            f"/v1/scores/{score_id}",
            replay_safe=True,
            missing=missing,
        )
    return _decode_requested_score(payload, scoreboard_url, score_id)


__all__ = [
    "PublishedScore",
    "pinned_cache_id",
    "published_by_pinned_cache_async",
    "published_by_pinned_cache_sync",
    "published_from_score",
    "published_score_async",
    "published_score_sync",
]
