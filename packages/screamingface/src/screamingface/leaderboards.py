"""Leaderboard discovery through the lazy default Client."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from screamingface._default_client import default_client
from screamingface.leaderboard import Leaderboard, LeaderboardInfo, LeaderboardScore
from screamingface.report import CandidateResult


def list() -> Sequence[LeaderboardInfo]:
    """List benchmarks registered with the configured public Scoreboard."""

    return default_client().leaderboards.list()


def get(benchmark_id: str, *, top: int = 50) -> Leaderboard:
    """Fetch one benchmark's ranked Leaderboard and imported baselines."""

    return default_client().leaderboards.get(benchmark_id, top=top)


def submit(candidate_result: CandidateResult) -> LeaderboardScore:
    """Publish one evaluated Candidate Result to its registered Leaderboard."""

    return default_client().leaderboards.submit(candidate_result)


def get_score(score_id: UUID | str) -> LeaderboardScore:
    """Fetch one public Scoreboard submission by its stable id."""

    return default_client().leaderboards.get_score(score_id)


__all__ = ["get", "get_score", "list", "submit"]
