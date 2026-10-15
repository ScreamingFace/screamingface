# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""Each Case's grading writes to its own inspect Transcript, released when the Case ends (OME-1607).

inspect records every model call of a scorer (a judge's `ModelEvent`, with the full prompt) in
the CURRENT Transcript, which lives in a ContextVar. The engine never reads it. If a Transcript
already sat in the context the aggregate was called in, every Case's task would inherit THAT
one and append to it — all judge calls of the run in one list, the memory the marking window
exists to bound. The grade hook therefore binds a fresh Transcript for each Case and puts the
caller's back when the Case ends.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.log._transcript import Transcript, init_transcript, transcript  # noqa: E402
from inspect_ai.scorer import Score, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402


def _request(case_id: int) -> GradeRequest:
    return GradeRequest(
        case_id=case_id,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text="Paris."),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )


@pytest.mark.asyncio
async def test_a_case_s_scorer_never_writes_to_the_caller_s_transcript() -> None:
    shared = Transcript()
    init_transcript(shared)  # a Transcript already in the aggregate's context
    seen: list[Transcript] = []

    async def scorer(state: TaskState, target: Target) -> Score:
        seen.append(transcript())
        return Score(value="C")

    hook = inspect_grade_case(scorer)
    await hook(_request(1))
    await hook(_request(2))

    assert len(seen) == 2
    assert all(case_transcript is not shared for case_transcript in seen)
    assert seen[0] is not seen[1]  # one Transcript per Case, never shared between Cases
    assert transcript() is shared  # the caller's Transcript is back once the Case ends
