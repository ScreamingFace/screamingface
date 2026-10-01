"""URL4 adapters for early canonical grading and authoritative final reduction."""

from collections.abc import Callable
from functools import lru_cache

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.grading_endpoints import (
    aggregate_endpoint,
    async_aggregate_endpoint,
)
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring
from url4.core.errors import ResolutionError
from url4.peer.server import Request


class CaseFinalizationError(ResolutionError):
    """Invalid grade transport cannot be downgraded to a missing case."""


def case_result_endpoint(load: Callable[[int], Scoring], *, available_case_count: int):
    # WHY: installed assets are immutable; retain only one selection to avoid rereading
    # the whole answer key for every case without an unbounded per-limit cache.
    selection = lru_cache(maxsize=1)(load)

    @observe_phase(ActivityKind.GRADING)
    async def endpoint(request: Request) -> str:
        try:
            index_text, count_text = request.intent.split(":")
            index, count = int(index_text), int(count_text)
            if not 0 < count <= available_case_count or not 0 <= index < count:
                raise ValueError("invalid selected Case position")
            return await selection(count).grade_row(request.context, index)
        # Grader crashes must abort just as they do in batch aggregation.
        # Cancellation remains outside this boundary (BaseException).
        except Exception as exc:
            raise CaseFinalizationError(
                "could not finalize Case grade", code="benchmark_contract_error", permanent=True
            ) from exc

    return endpoint


def aggregate_result_endpoint(
    *, label: str, available_case_count: int, load: Callable[[int], Scoring]
):
    async def aggregate(raw: str, count: int):
        scoring = load(count)
        try:
            return await scoring.finish(raw)
        except ValueError as exc:
            raise CaseFinalizationError(
                "invalid completed Case results", code="benchmark_contract_error", permanent=True
            ) from exc

    return async_aggregate_endpoint(
        label=label, available_case_count=available_case_count, aggregate=aggregate
    )


def batch_result_endpoint(*, label: str, available_case_count: int, load: Callable[[int], Scoring]):
    """Keep published batch expressions valid under their unchanged scoring revision."""
    return aggregate_endpoint(
        label=label,
        available_case_count=available_case_count,
        aggregate=lambda raw, count: load(count).aggregate(raw),
    )
