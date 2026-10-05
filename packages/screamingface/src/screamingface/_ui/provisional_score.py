"""Validate cumulative score snapshots independently of activity wording."""

import math
from dataclasses import dataclass
from typing import cast

from screamingface.events import Log


@dataclass(frozen=True)
class ProvisionalScore:
    identity: tuple[str, str, str]
    revision: int
    completed: int
    graded: int
    score: float | None


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _score(value: object, graded: int) -> bool:
    if graded == 0:
        return value is None
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_snapshot(event: Log, total: int | None) -> ProvisionalScore | None:
    attrs = event.attributes
    if attrs.get("sf.progress.schema") != "screamingface.benchmark-progress.v1":
        return None
    board, version = attrs.get("sf.progress.benchmark"), attrs.get("sf.progress.benchmark_revision")
    revision, completed, graded = (
        attrs.get("sf.progress." + key) for key in ("revision", "completed", "graded")
    )
    if (
        not all(_integer(value) for value in (revision, completed, graded))
        or not isinstance(board, str)
        or not isinstance(version, str)
    ):
        return None
    # Values were checked above; explicit casts keep the transport boundary typed.
    return _validated(
        event.run_id,
        board,
        version,
        cast(int, revision),
        cast(int, completed),
        cast(int, graded),
        attrs.get("sf.progress.score"),
        total,
    )


def _validated(
    run: str,
    board: str,
    version: str,
    revision: int,
    completed: int,
    graded: int,
    score: object,
    total: int | None,
) -> ProvisionalScore | None:
    if not board or not version or revision < 1 or not 0 <= graded <= completed:
        return None
    if (total is not None and completed > total) or not _score(score, graded):
        return None
    return ProvisionalScore(
        (run, board, version), revision, completed, graded, cast(float | None, score)
    )


def advance(
    current: ProvisionalScore | None, incoming: ProvisionalScore | None
) -> ProvisionalScore | None:
    if incoming is None:
        return current
    if current is not None and (
        incoming.identity != current.identity
        or incoming.revision <= current.revision
        or incoming.completed < current.completed
    ):
        return current
    return incoming
