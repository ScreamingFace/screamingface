"""Leaderboard discovery through the lazy default Client."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from screamingface._default_client import default_client
from screamingface._scoreboard.leaderboards import _UNSET, _Unset
from screamingface.leaderboard import (
    Leaderboard,
    LeaderboardInfo,
    LeaderboardScore,
    ScoreMetadataEvent,
)
from screamingface.report import CandidateResult


def list() -> Sequence[LeaderboardInfo]:
    """List benchmarks registered with the configured public Scoreboard."""

    return default_client().leaderboards.list()


def get(benchmark_id: str, *, top: int = 50) -> Leaderboard:
    """Fetch one benchmark's ranked Leaderboard and imported baselines."""

    return default_client().leaderboards.get(benchmark_id, top=top)


def submit(
    candidate_result: CandidateResult,
    *,
    authors: Sequence[str] | None = None,
    paper_url: str | None = None,
    authors_metadata: Mapping[str, Mapping[str, object]] | None = None,
    paper_metadata: Mapping[str, object] | None = None,
) -> LeaderboardScore:
    """Publish one evaluated Candidate Result to its registered Leaderboard."""

    leaderboards = default_client().leaderboards
    # WHY: absence is forwarded as absence, so older or fake Leaderboards implementations keep
    # working.
    optional: dict[str, Any] = {
        name: value
        for name, value in (
            ("paper_url", paper_url),
            ("authors_metadata", authors_metadata),
            ("paper_metadata", paper_metadata),
        )
        if value is not None
    }
    return leaderboards.submit(candidate_result, authors=authors, **optional)


def get_score(score_id: UUID | str) -> LeaderboardScore:
    """Fetch one public Scoreboard submission by its stable id."""

    return default_client().leaderboards.get_score(score_id)


def edit(
    score_id: UUID | str,
    *,
    authors: Sequence[str] | None | _Unset = _UNSET,
    paper_url: str | None | _Unset = _UNSET,
    authors_metadata: Mapping[str, Mapping[str, object]] | None | _Unset = _UNSET,
    paper_metadata: Mapping[str, object] | None | _Unset = _UNSET,
) -> LeaderboardScore:
    """Change the authors, paper link or metadata of a score you submitted.

    An omitted field is unchanged; `None` clears it (the `_UNSET` default keeps the two apart).
    """

    # WHY: legacy implementations need absent arguments omitted; explicit None still clears.
    fields: dict[str, Any] = {
        name: value
        for name, value in (
            ("authors", authors),
            ("paper_url", paper_url),
            ("authors_metadata", authors_metadata),
            ("paper_metadata", paper_metadata),
        )
        if value is not _UNSET
    }
    return default_client().leaderboards.edit(score_id, **fields)


def metadata_events(score_id: UUID | str) -> tuple[ScoreMetadataEvent, ...]:
    """Read the edit log of a score you submitted, newest first."""

    return default_client().leaderboards.metadata_events(score_id)


__all__ = ["edit", "get", "get_score", "list", "metadata_events", "submit"]
