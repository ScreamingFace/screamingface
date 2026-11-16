# pyright: reportMissingImports=false
"""The judged aggregate's model face is the object its dict face dumps.

FEATURE: memory fix 3 (OME-1835), unit 1. The judged route now returns the CandidateResult
model. The v1 wire dict stays the model's `as_payload()`, so the two faces never disagree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.dataset import Sample  # noqa: E402
from test_single_turn_judged_imports import _ScriptedNode  # noqa: E402
from test_whole_run_metric import _row  # noqa: E402

from screamingface_engine.benchmarks.contract import CandidateResult  # noqa: E402
from screamingface_engine.request_scope import RequestScope, request_scope  # noqa: E402
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from screamingface_engine_inspect.prepare import (  # noqa: E402
    TASK_REPLAY_CASES,
    _write_cases,
    prepared_case,
)
from screamingface_engine_inspect.single_shot import (  # noqa: E402
    _judged_aggregate,
    _judged_aggregate_result,
)


@pytest.mark.asyncio
async def test_the_judged_result_face_is_the_model_the_dict_face_dumps(tmp_path: Path) -> None:
    samples: list[Sample] = [
        Sample(id=index, input=question, target=gold)
        for index, (question, gold) in enumerate(
            [("Capital of Uganda?", "Kampala"), ("Year Inspect launched?", "2024"), ("?", "x")],
            start=1,
        )
    ]
    cases = [
        prepared_case(sample, index, str(sample.input), TASK_REPLAY_CASES["simpleqa"])
        for index, sample in enumerate(samples, start=1)
    ]
    _write_cases(cases, tmp_path)
    rows: str = json.dumps(
        [_row(index, reply) for index, reply in enumerate(["Kampala", "2019", "I don't know."], 1)]
    )
    as_dict: dict[str, Any]
    model: CandidateResult
    with request_scope(RequestScope(origin="run")):
        as_dict = await _judged_aggregate(
            imported_benchmark("simpleqa"),  # type: ignore[arg-type]
            tmp_path,
            _ScriptedNode(["A", "B", "C"]),  # type: ignore[arg-type]
        )(rows, (1, 2, 3))
        model = await _judged_aggregate_result(
            imported_benchmark("simpleqa"),  # type: ignore[arg-type]
            tmp_path,
            _ScriptedNode(["A", "B", "C"]),  # type: ignore[arg-type]
        )(rows, (1, 2, 3))
    assert isinstance(model, CandidateResult)
    assert model.as_payload() == as_dict
