"""Public card summaries without the per-board ranking/frontier read fan-out."""

import logging
from typing import Any

from pydantic import BaseModel, FiniteFloat
from pypika_tortoise.analytics import RowNumber
from pypika_tortoise.enums import Order
from pypika_tortoise.queries import Query, QueryBuilder
from tortoise import Tortoise
from tortoise.exceptions import FieldError
from tortoise.expressions import Q
from tortoise.query_api import execute_pypika

from .models import Benchmark, Score

logger = logging.getLogger(__name__)


class BenchmarkSummary(BaseModel):
    id: str
    display_name: str
    description: str | None
    focus: str | None
    best_score: FiniteFloat | None


class _Candidate(BaseModel):
    score: FiniteFloat
    ran_with_providers: list[str]


def _ranked_candidates() -> QueryBuilder:
    benchmarks, scores = Benchmark.get_table(), Score.get_table()
    # Match _build_leaderboard_query: newest best run per spec/revision,
    # then the earliest claim among tied specs. A corrupt selected row must
    # not be replaced with a lower row that top=1 would never have returned.
    per_spec = (
        RowNumber()
        .over(scores.benchmark_id, scores.spec_id, scores.benchmark_revision)
        .orderby(scores.score, order=Order.desc)
        .orderby(scores.submitted_at, order=Order.desc)
        .as_("spec_rank")
    )
    ranked = (
        Query.from_(scores)
        .join(benchmarks)
        .on(scores.benchmark_id == benchmarks.id)
        .where(benchmarks.revision.isnull() | (scores.benchmark_revision == benchmarks.revision))
        .where(benchmarks.case_count.isnull() | (scores.total_questions >= benchmarks.case_count))
        .select(
            scores.benchmark_id,
            scores.spec_id,
            scores.score,
            scores.ran_with_providers,
            scores.submitted_at,
            per_spec,
        )
        .as_("ranked")
    )
    per_board = (
        RowNumber()
        .over(ranked.benchmark_id)
        .orderby(ranked.score, order=Order.desc)
        .orderby(ranked.submitted_at, order=Order.asc)
        .as_("board_rank")
    )
    return (
        Query.from_(ranked)
        .where(ranked.spec_rank == 1)
        .select(
            ranked.benchmark_id, ranked.spec_id, ranked.score, ranked.ran_with_providers, per_board
        )
        .as_("candidates")
    )


def _candidate_score(row: dict[str, Any]) -> float | None:
    if row["spec_id"] is None:
        return None
    try:
        # Same ORM field decoder used by the detailed board's _to_python_rows.
        # Providers is its only non-nullable raw JSON/decimal field: unreadable
        # authors or costs degrade in place and must not hide a valid score.
        providers = Score._meta.fields_map["ran_with_providers"].to_python_value(
            row["ran_with_providers"]
        )
        return _Candidate(score=row["score"], ran_with_providers=providers).score
    except (ValueError, FieldError):
        logger.warning(
            "Unreadable catalog candidate on benchmark_id=%s spec_id=%s; serving no score",
            row["id"],
            row["spec_id"],
        )
        return None


async def _revalidate_visibility() -> set[str]:
    # INVARIANT: the last database await before publishing scores checks fresh
    # visibility, just like the detailed board. One bulk check, not one per row.
    rows = await Benchmark.filter(Q(visibility__isnull=True) | ~Q(visibility="private")).values(
        "id"
    )
    return {row["id"] for row in rows}


async def list_benchmark_summaries() -> list[BenchmarkSummary]:
    benchmarks, candidates = Benchmark.get_table(), _ranked_candidates()
    query = (
        Query.from_(benchmarks)
        .left_join(candidates)
        .on((candidates.benchmark_id == benchmarks.id) & (candidates.board_rank == 1))
        .select(
            benchmarks.id,
            benchmarks.display_name,
            benchmarks.description,
            benchmarks.focus,
            candidates.spec_id,
            candidates.score,
            candidates.ran_with_providers,
        )
        .where(benchmarks.visibility.isnull() | (benchmarks.visibility != "private"))
        .orderby(benchmarks.id)
    )
    # Scope and score selection share a statement snapshot. Transfer at most one
    # candidate per board; one unreadable candidate cannot fail the whole catalog.
    result = await execute_pypika(query, using_db=Tortoise.get_connection("default"))
    public_ids = await _revalidate_visibility()
    return [
        BenchmarkSummary.model_validate({**row, "best_score": _candidate_score(row)})
        for row in result.rows
        if row["id"] in public_ids
    ]
