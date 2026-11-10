from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from pydantic import ValidationError
from tortoise import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from scoreboard.classification.openness import Openness
from scoreboard.db import DEFAULT_CONNECTION

from .baseline_comparison import validate_comparison
from .baseline_history import preserve_legacy_observation, record_observation
from .models import Baseline, Benchmark
from .schemas import BaselineImportRow, BaselineSchema

logger = logging.getLogger(__name__)


def _baseline_to_schema(model: Baseline, benchmark: Benchmark | None = None) -> BaselineSchema:
    result = BaselineSchema(
        id=model.id,
        benchmark_id=cast(str, getattr(model, "benchmark_id")),
        model_name=model.model_name,
        score=model.score,
        source=model.source,
        source_url=model.source_url,
        imported_at=model.imported_at,
        last_imported_at=model.last_imported_at,
        metric_name=model.metric_name,
        observed_at=model.observed_at,
        metadata=model.metadata,
        observation_revision=model.observation_revision,
        observation_updated_at=model.observation_updated_at,
        # WHY: tortoise-orm >=1.1.8 types CharField as `str | None`, which no longer
        # satisfies the schema's `Openness | None`. The DB column is a bare CharField, so
        # the narrowing is ours to assert; Pydantic still rejects a junk value on
        # construction, which is what actually enforces the invariant at runtime.
        openness_override=cast(Openness | None, model.openness_override),
    )
    result.ranking_eligible = _ranking_eligible(result, model.attached_by, benchmark)
    return result


def _ranking_eligible(
    row: BaselineSchema,
    attached_by: str | None,
    benchmark: Benchmark | None,
) -> bool:
    if benchmark is None or not row.metadata or "comparison" not in row.metadata:
        return False
    try:
        data = row.model_dump(
            exclude={
                "id",
                "imported_at",
                "last_imported_at",
                "openness_override",
                "ranking_eligible",
                "observation_revision",
                "observation_updated_at",
            }
        )
        candidate = BaselineImportRow.model_validate({**data, "attached_by": attached_by})
        return validate_comparison(
            candidate, revision=benchmark.revision, case_count=benchmark.case_count
        )
    except ValueError:
        # WHY: stale or malformed evidence must not take down the board or inherit approval.
        return False


class BaselineStore:
    """Persistence for imported single-model baselines ('line to beat').

    # WHY: a separate store (not folded into ScoreStore) because a Baseline is a
    # distinct concept from a community Score submission — no url4_expression, no
    # provider info, no correctness counts. Community and baseline rows never share
    # a table.
    """

    async def import_baseline(
        self,
        row: BaselineImportRow,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> BaselineSchema:
        # INVARIANT: a baseline can only be imported against a benchmark that already
        # exists, mirroring the check the /v1/scores route performs before ScoreStore
        # sees a submission (see routes/scores.py::submit_score).
        benchmark = await Benchmark.filter(id=row.benchmark_id).using_db(using_db).first()
        if benchmark is None:
            raise ValueError(f"unknown benchmark_id: {row.benchmark_id!r}")
        validate_comparison(row, revision=benchmark.revision, case_count=benchmark.case_count)

        # INVARIANT: the upsert's row lock survives until its timestamp is saved.
        # Stamp after locking, never while building defaults before a contended write.
        connection_name = using_db.connection_name if using_db else DEFAULT_CONNECTION
        async with in_transaction(connection_name=connection_name) as connection:
            await preserve_legacy_observation(row, connection)
            baseline, _ = await Baseline.update_or_create(
                benchmark_id=row.benchmark_id,
                model_name=row.model_name,
                source=row.source,
                defaults={
                    "score": row.score,
                    "source_url": row.source_url,
                    "metadata": row.metadata,
                    # WHY: imports replace an observation, not patch it. Missing
                    # provenance must not carry an old read date onto a new score.
                    "metric_name": row.metric_name,
                    "observed_at": row.observed_at,
                    "attached_by": row.attached_by,
                },
                using_db=connection,
            )
            baseline.last_imported_at = max(
                datetime.now(UTC),
                baseline.imported_at,
                baseline.last_imported_at or baseline.imported_at,
            )
            await record_observation(baseline, connection)
            await baseline.save(
                using_db=connection,
                update_fields=[
                    "last_imported_at",
                    "observation_revision",
                    "observation_updated_at",
                ],
            )
        return _baseline_to_schema(baseline, benchmark)

    async def import_many(self, rows: Sequence[BaselineImportRow]) -> list[BaselineSchema]:
        # INVARIANT: all-or-nothing — if any row in the batch fails (e.g. an unknown
        # benchmark_id), no row from this batch is left persisted (found in PR review:
        # a mid-batch failure used to leave earlier rows committed).
        async with in_transaction(connection_name=DEFAULT_CONNECTION) as connection:
            return [await self.import_baseline(row, using_db=connection) for row in rows]

    async def list_baselines(self, benchmark_id: str) -> list[BaselineSchema]:
        benchmark = await Benchmark.get_or_none(id=benchmark_id)
        rows = await Baseline.filter(benchmark_id=benchmark_id).order_by("-score")
        # INVARIANT: one row that fails schema validation (e.g. metadata written
        # before the bound existed, or inserted outside the import path) must not
        # take down the whole board — skip it, keep serving every valid row
        # (found in PR review: this used to be an unhandled 500 for everyone).
        baselines: list[BaselineSchema] = []
        for baseline in rows:
            try:
                baselines.append(_baseline_to_schema(baseline, benchmark))
            except ValidationError:
                logger.warning("skipping baseline %s: failed schema validation", baseline.id)
        return baselines
