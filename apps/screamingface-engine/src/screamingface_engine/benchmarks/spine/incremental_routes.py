"""URL4 adapters for early canonical grading and authoritative final reduction."""

from collections.abc import Callable
from functools import lru_cache

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.evaluation import async_aggregate_endpoint
from screamingface_engine.benchmarks.spine.incremental import Scoring
from screamingface_engine.benchmarks.stages import observe_stage
from url4.core.errors import ResolutionError
from url4.peer.server import Request


class CaseFinalizationError(ResolutionError):
    """Invalid grade transport cannot be downgraded to a missing case."""


def case_result_endpoint(load: Callable[[int], Scoring]):
    # WHY: installed assets are immutable; retain only one selection to avoid rereading
    # the whole answer key for every case without an unbounded per-limit cache.
    selection = lru_cache(maxsize=1)(load)

    @observe_stage(ActivityKind.GRADING)
    async def endpoint(request: Request) -> str:
        try:
            index_text, count_text = request.intent.split(":")
            index, count = int(index_text), int(count_text)
            if not 0 <= index < count:
                raise ValueError("invalid selected Case position")
            return await selection(count).grade_row(request.context, index)
        except (OSError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise CaseFinalizationError(
                "could not finalize Case grade", code="benchmark_contract_error", permanent=True
            ) from exc

    return endpoint


def aggregate_result_endpoint(
    *, label: str, available_case_count: int, load: Callable[[int], Scoring]
):
    async def aggregate(raw: str, count: int):
        return await load(count).finish(raw)

    return async_aggregate_endpoint(
        label=label, available_case_count=available_case_count, aggregate=aggregate
    )
