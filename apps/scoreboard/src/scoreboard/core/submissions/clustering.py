"""Pure rules of the clustered submit (E14, OME-1307).

INVARIANT: standard library only. It takes primitive values, so it needs no pydantic, no Tortoise
and no FastAPI.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID


def result_labels(
    *,
    coverage_status: str | None,
    entry_count: int | None,
    call_count: int | None,
    replayed_from_result_id: UUID | None,
    replay_hits: int | None,
    replay_misses: int | None,
) -> list[str]:
    """The labels of one result, partial cache first, then replay. No label otherwise.

    WHY `entry_count of call_count`: the receipt carries `n` (entries) and `c` (calls), not a
    missing count (spec gap G6, decided (default)).
    """
    labels: list[str] = []
    if coverage_status == "partial":
        labels.append(f"partial cache ({entry_count} of {call_count} calls)")
    if replayed_from_result_id is not None:
        hits, misses = replay_hits or 0, replay_misses or 0
        labels.append(f"replay of {replayed_from_result_id} ({hits}/{hits + misses})")
    return labels


def publication_needed(receipt: Mapping[str, object]) -> bool:
    """SC-D8: a result that carries a cache version gets a `private` publication row."""
    return receipt["cache_version_id"] is not None
