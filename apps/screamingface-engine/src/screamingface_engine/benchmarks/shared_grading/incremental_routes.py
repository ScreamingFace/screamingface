"""URL4 code for early canonical grading and authoritative final reduction (spec R1).

``(…, execution, case_index, case_count)!/…/aggregate/case-result`` grades one Case as it
finishes; ``(evaluations, selected)!/…/aggregate/graded`` reduces the run.
"""

import json
from collections.abc import Callable
from functools import lru_cache

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_evaluation import aggregate_code, text_input
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.protocol import (
    CASE_COUNT_SOURCE,
    CASE_INDEX_SOURCE,
    EXECUTION_SOURCE,
)
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring
from url4 import CodeCall, CodeHandler
from url4.core.errors import ResolutionError
from url4.dag import collected_error


class CaseFinalizationError(ResolutionError):
    """Invalid grade transport cannot be downgraded to a missing case."""


def case_result_code(load: Callable[[int], Scoring], *, available_case_count: int) -> CodeHandler:
    """Grade one finished Case from its ``execution`` row and its selected position."""

    # WHY: installed assets are immutable; retain only one selection to avoid rereading
    # the whole answer key for every case without an unbounded per-limit cache.
    selection = lru_cache(maxsize=1)(load)

    @observe_phase(ActivityKind.GRADING)
    async def handler(call: CodeCall) -> str:
        try:
            index = int(text_input(call, CASE_INDEX_SOURCE))
            count = int(text_input(call, CASE_COUNT_SOURCE))
            if not 0 < count <= available_case_count or not 0 <= index < count:
                raise ValueError("invalid selected Case position")
            return await selection(count).grade_row(text_input(call, EXECUTION_SOURCE), index)
        # Grader crashes must abort just as they do in batch aggregation.
        # Cancellation remains outside this boundary (BaseException).
        except Exception as exc:
            failure = CaseFinalizationError(
                "could not finalize Case grade", code="benchmark_contract_error", permanent=True
            )
            failure.__cause__ = exc
            # WHY return the collected row, not raise: url4 reports any failing code call as
            # `intent_error` (Spec C §13.6), which hides the `CaseFinalizationError` kind that
            # `Scoring.finish` keys on to abort the run. This is byte for byte the row the
            # retired endpoint's raise left in the iteration.
            return json.dumps(collected_error(failure))

    return handler


def graded_result_code(
    *, label: str, available_case_count: int, load: Callable[[int], Scoring]
) -> CodeHandler:
    """Reduce the run's early-graded Case results into the report."""

    async def aggregate(raw: str, count: int):
        scoring = load(count)
        try:
            return await scoring.finish(raw)
        except ValueError as exc:
            raise CaseFinalizationError(
                "invalid completed Case results", code="benchmark_contract_error", permanent=True
            ) from exc

    return aggregate_code(
        label=label, available_case_count=available_case_count, aggregate=aggregate
    )
