"""Version observations under the importer's row lock, never version a refresh."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tortoise import BaseDBAsyncClient

from .models import Baseline, BaselineRevision
from .schemas import BaselineImportRow


def observation(baseline: Baseline) -> dict[str, Any]:
    # INVARIANT: explicit public fields only; attribution has its own private column.
    return {
        "score": baseline.score,
        "source_url": baseline.source_url,
        "metric_name": baseline.metric_name,
        "observed_at": baseline.observed_at.isoformat() if baseline.observed_at else None,
        "metadata": baseline.metadata,
    }


async def preserve_legacy_observation(
    row: BaselineImportRow, connection: BaseDBAsyncClient
) -> None:
    # WHY: normal rows already have a snapshot. Only legacy rows need their
    # pre-upsert value captured. Re-check revision=0 under the lock so overlapping
    # first edits cannot seed conflicting versions or lose the old value.
    legacy = (
        await Baseline.filter(
            benchmark_id=row.benchmark_id,
            model_name=row.model_name,
            source=row.source,
            observation_revision=0,
        )
        .using_db(connection)
        .select_for_update()
        .first()
    )
    if legacy is None:
        return
    await BaselineRevision.create(
        baseline=legacy,
        revision=1,
        observation=observation(legacy),
        attached_by=legacy.attached_by,
        recorded_at=None,
        using_db=connection,
    )
    legacy.observation_revision = 1
    await legacy.save(using_db=connection, update_fields=["observation_revision"])


async def record_observation(baseline: Baseline, connection: BaseDBAsyncClient) -> None:
    current = observation(baseline)
    previous = (
        await BaselineRevision.filter(
            baseline_id=baseline.id,
            revision=baseline.observation_revision,
        )
        .using_db(connection)
        .first()
    )
    # WHY: JSONB can return exponent numbers as integers; representation is not an edit.
    if (
        previous
        and _same_json(previous.observation, current)
        and previous.attached_by == baseline.attached_by
    ):
        return
    # INVARIANT: upsert's lock remains held through snapshot and current-row save.
    # Concurrent imports compare with the last committed version, not an earlier read.
    baseline.observation_revision += 1
    if previous:
        baseline.observation_updated_at = baseline.last_imported_at
    await BaselineRevision.create(
        baseline=baseline,
        revision=baseline.observation_revision,
        observation=current,
        attached_by=baseline.attached_by,
        recorded_at=baseline.last_imported_at,
        using_db=connection,
    )


def _same_json(left: Any, right: Any) -> bool:
    """Compare JSON values without mistaking booleans for numbers or numeric spelling for edits."""
    if isinstance(left, bool) or isinstance(right, bool):
        equal = type(left) is type(right) and left == right
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        # WHY decimal text: JSONB stores the JSON decimal, not the float's binary
        # approximation (e.g. 1e23). Converting through float would lose integer precision.
        equal = Decimal(str(left)) == Decimal(str(right))
    elif isinstance(left, dict) and isinstance(right, dict):
        equal = left.keys() == right.keys() and all(
            _same_json(value, right[key]) for key, value in left.items()
        )
    elif isinstance(left, list) and isinstance(right, list):
        equal = len(left) == len(right) and all(
            _same_json(a, b) for a, b in zip(left, right, strict=True)
        )
    else:
        equal = type(left) is type(right) and left == right
    return equal
