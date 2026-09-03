from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import cast

from pydantic import ValidationError
from tortoise import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from scoreboard.classification.openness import Openness

from .models import Baseline, Benchmark
from .schemas import BaselineImportRow, BaselineSchema

logger = logging.getLogger(__name__)


def _baseline_to_schema(model: Baseline) -> BaselineSchema:
    return BaselineSchema(
        id=model.id,
        benchmark_id=cast(str, getattr(model, "benchmark_id")),
        model_name=model.model_name,
        score=model.score,
        source=model.source,
        source_url=model.source_url,
        imported_at=model.imported_at,
        metadata=model.metadata,
        # WHY: tortoise-orm >=1.1.8 types CharField as `str | None`, which no longer
        # satisfies the schema's `Openness | None`. The DB column is a bare CharField, so
        # the narrowing is ours to assert; Pydantic still rejects a junk value on
        # construction, which is what actually enforces the invariant at runtime.
        openness_override=cast(Openness | None, model.openness_override),
    )


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
        exists = await Benchmark.filter(id=row.benchmark_id).using_db(using_db).exists()
        if not exists:
            raise ValueError(f"unknown benchmark_id: {row.benchmark_id!r}")

        baseline, _ = await Baseline.update_or_create(
            benchmark_id=row.benchmark_id,
            model_name=row.model_name,
            source=row.source,
            defaults={
                "score": row.score,
                "source_url": row.source_url,
                "metadata": row.metadata,
            },
            using_db=using_db,
        )
        return _baseline_to_schema(baseline)

    async def import_many(self, rows: Sequence[BaselineImportRow]) -> list[BaselineSchema]:
        # INVARIANT: all-or-nothing — if any row in the batch fails (e.g. an unknown
        # benchmark_id), no row from this batch is left persisted (found in PR review:
        # a mid-batch failure used to leave earlier rows committed).
        async with in_transaction() as connection:
            return [await self.import_baseline(row, using_db=connection) for row in rows]

    async def list_baselines(self, benchmark_id: str) -> list[BaselineSchema]:
        rows = await Baseline.filter(benchmark_id=benchmark_id).order_by("-score")
        # INVARIANT: one row that fails schema validation (e.g. metadata written
        # before the bound existed, or inserted outside the import path) must not
        # take down the whole board — skip it, keep serving every valid row
        # (found in PR review: this used to be an unhandled 500 for everyone).
        baselines: list[BaselineSchema] = []
        for baseline in rows:
            try:
                baselines.append(_baseline_to_schema(baseline))
            except ValidationError:
                logger.warning("skipping baseline %s: failed schema validation", baseline.id)
        return baselines
