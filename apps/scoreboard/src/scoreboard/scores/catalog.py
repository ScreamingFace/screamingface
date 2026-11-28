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

from scoreboard.classification.candidate_kind import CandidateKindVerdict, classify_candidate_kind

from .baseline_store import BaselineStore
from .models import Benchmark, Score

logger = logging.getLogger(__name__)


class BenchmarkSummary(BaseModel):
    id: str
    display_name: str
    description: str | None
    focus: str | None
    best_score: FiniteFloat | None
    # FEATURE: OME-1916 — does the best FUSION score on this benchmark beat the best
    # SOLO-MODEL score, classified only via `classify_candidate_kind` (OME-1852), never
    # inferred from spec_id/provider count. A benchmark with no fusion submission, or no
    # solo-model submission, cannot have a fusion win: it reads False, never True by
    # default. This is a direct max-vs-max comparison, independent of cost/Pareto standing
    # (OME-1282/OME-1852), which is a separate, already-shipped concept.
    fusion_leads: bool


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
            scores.metadata,
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
            ranked.benchmark_id,
            ranked.spec_id,
            ranked.score,
            ranked.ran_with_providers,
            ranked.metadata,
            per_board,
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


def _row_candidate_kind(row: dict[str, Any]) -> CandidateKindVerdict:
    """A ranked candidate row's composition verdict, decoded the same fail-closed way
    `_candidate_score` decodes `ran_with_providers`: no candidate on this row, or
    unreadable `metadata`, is "unknown" — never a guess.
    """
    if row["spec_id"] is None:
        return "unknown"
    try:
        metadata = Score._meta.fields_map["metadata"].to_python_value(row["metadata"])
    except (ValueError, FieldError):
        logger.warning(
            "Unreadable candidate_kind metadata on benchmark_id=%s spec_id=%s; classifying unknown",
            row["id"],
            row["spec_id"],
        )
        return "unknown"
    return classify_candidate_kind(metadata)


def _fusion_leads_verdict(best_by_kind: dict[CandidateKindVerdict, float]) -> bool:
    """OME-1916's decided criterion: best fusion score beats best solo-model score, a
    direct max-vs-max comparison. Neither group present, or only one of the two, cannot
    be a fusion win.
    """
    fusion, model = best_by_kind.get("fusion"), best_by_kind.get("model")
    return fusion is not None and model is not None and fusion > model


async def _revalidate_visibility() -> set[str]:
    # INVARIANT: the last database await before publishing scores checks fresh
    # visibility, just like the detailed board. One bulk check, not one per row.
    rows = await Benchmark.filter(Q(visibility__isnull=True) | ~Q(visibility="private")).values(
        "id"
    )
    return {row["id"] for row in rows}


def _best_score(row: dict[str, Any], imported: dict[str, float]) -> float | None:
    candidates = [_candidate_score(row), imported.get(row["id"])]
    return max((score for score in candidates if score is not None), default=None)


async def list_benchmark_summaries(*, include_imported: bool = False) -> list[BenchmarkSummary]:
    benchmarks, candidates = Benchmark.get_table(), _ranked_candidates()
    # WHY no `board_rank == 1` filter here (unlike before OME-1916): best_score still wants
    # only the single top-ranked candidate, but fusion_leads needs EVERY in-scope candidate
    # on the board to compare the fusion group's max against the model group's max. Reading
    # every rank in this one join — instead of a second query filtered to the top rank, or a
    # separate fusion/model query — keeps the summary endpoint at the two DB statements
    # `test_summary_uses_two_database_statements` pins (this join, then `_revalidate_visibility`
    # below): one more row per extra spec on a board, not one more statement.
    query = (
        Query.from_(benchmarks)
        .left_join(candidates)
        .on(candidates.benchmark_id == benchmarks.id)
        .select(
            benchmarks.id,
            benchmarks.display_name,
            benchmarks.description,
            benchmarks.focus,
            candidates.board_rank,
            candidates.spec_id,
            candidates.score,
            candidates.ran_with_providers,
            candidates.metadata,
        )
        .where(benchmarks.visibility.isnull() | (benchmarks.visibility != "private"))
        .orderby(benchmarks.id)
    )
    # Scope and score selection share a statement snapshot. One unreadable candidate
    # cannot fail the whole catalog.
    result = await execute_pypika(query, using_db=Tortoise.get_connection("default"))
    board_order: list[str] = []
    top_candidate: dict[str, dict[str, Any]] = {}
    best_by_kind: dict[str, dict[CandidateKindVerdict, float]] = {}
    for row in result.rows:
        board_id = row["id"]
        if board_id not in top_candidate:
            board_order.append(board_id)
            top_candidate[board_id] = row  # placeholder; replaced below if a ranked row exists
        if row["board_rank"] == 1:
            top_candidate[board_id] = row
        kind = _row_candidate_kind(row)
        if kind == "unknown":
            continue
        per_board = best_by_kind.setdefault(board_id, {})
        if kind not in per_board or row["score"] > per_board[kind]:
            per_board[kind] = row["score"]
    # WHY opt-in: page indexing counts every displayed result; the homepage API's existing
    # community-score contract stays unchanged. The bulk join avoids a read per board.
    imported = await BaselineStore().best_ranked_scores(board_order) if include_imported else {}
    # INVARIANT: revalidate AFTER the imported-result read, immediately before publication.
    public_ids = await _revalidate_visibility()
    return [
        BenchmarkSummary.model_validate(
            {
                **top_candidate[board_id],
                "best_score": _best_score(top_candidate[board_id], imported),
                "fusion_leads": _fusion_leads_verdict(best_by_kind.get(board_id, {})),
            }
        )
        for board_id in board_order
        if board_id in public_ids
    ]
