"""Leaderboard discovery through the lazy default Client."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from screamingface._default_client import default_client
from screamingface._scoreboard.leaderboards import UNSET, _Unset
from screamingface.leaderboard import Leaderboard, LeaderboardInfo, LeaderboardScore
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
    revision_of: str | None = None,
) -> LeaderboardScore:
    """Publish one evaluated Candidate Result to its registered Leaderboard."""

    # Send an optional keyword only when the caller gave it, so a board before E14a still
    # accepts a normal submit. A later optional keyword adds one entry here, not a branch.
    given: dict[str, str] = {}
    if paper_url is not None:
        given["paper_url"] = paper_url
    if revision_of is not None:
        given["revision_of"] = revision_of
    return default_client().leaderboards.submit(candidate_result, authors=authors, **given)


def get_score(score_id: UUID | str) -> LeaderboardScore:
    """Fetch one public Scoreboard submission by its stable id."""

    return default_client().leaderboards.get_score(score_id)


def update_submission(
    score_id: UUID | str,
    *,
    expected_revision: int,
    authors: Sequence[str] | None | _Unset = UNSET,
    paper_url: str | None | _Unset = UNSET,
) -> LeaderboardScore:
    """Edit the authors or the paper URL of one submission you own."""

    return default_client().leaderboards.update_submission(
        score_id,
        expected_revision=expected_revision,
        authors=authors,
        paper_url=paper_url,
    )


__all__ = ["get", "get_score", "list", "submit", "update_submission"]
