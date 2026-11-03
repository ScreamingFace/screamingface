"""Public card summaries without the per-board ranking/frontier read fan-out."""

from pydantic import BaseModel
from pypika_tortoise.functions import Max
from pypika_tortoise.queries import Query
from tortoise import Tortoise
from tortoise.expressions import Q
from tortoise.query_api import execute_pypika

from .models import Benchmark, Score


class BenchmarkSummary(BaseModel):
    id: str
    display_name: str
    description: str | None
    focus: str | None
    best_score: float | None


async def _revalidate_visibility() -> set[str]:
    # INVARIANT: the last database await before publishing scores checks fresh
    # visibility, just like the detailed board. One bulk check, not one per row.
    rows = await Benchmark.filter(Q(visibility__isnull=True) | ~Q(visibility="private")).values(
        "id"
    )
    return {row["id"] for row in rows}


async def list_benchmark_summaries() -> list[BenchmarkSummary]:
    benchmarks, scores = Benchmark.get_table(), Score.get_table()
    columns = [benchmarks.id, benchmarks.display_name, benchmarks.description, benchmarks.focus]
    # INVARIANT: the join uses the SAME revision and complete-run eligibility as
    # _build_leaderboard_query. MAX over each spec's maximum equals MAX over all
    # eligible submissions, so the scalar needs no window or per-spec metadata.
    # No verified flag filter: the existing homepage's bestEntryScore includes all
    # ranked entries, not baselines, regardless of that flag.
    eligible = (
        (scores.benchmark_id == benchmarks.id)
        & (benchmarks.revision.isnull() | (scores.benchmark_revision == benchmarks.revision))
        & (benchmarks.case_count.isnull() | (scores.total_questions >= benchmarks.case_count))
    )
    query = (
        Query.from_(benchmarks)
        .left_join(scores)
        .on(eligible)
        .select(*columns, Max(scores.score).as_("best_score"))
        .where(benchmarks.visibility.isnull() | (benchmarks.visibility != "private"))
        .groupby(*columns)
        .orderby(benchmarks.id)
    )
    # WHY grouped: registered scope and scores share a statement snapshot; the
    # final bulk visibility check closes a flip during that aggregate read.
    result = await execute_pypika(query, using_db=Tortoise.get_connection("default"))
    public_ids = await _revalidate_visibility()
    return [BenchmarkSummary.model_validate(row) for row in result.rows if row["id"] in public_ids]
