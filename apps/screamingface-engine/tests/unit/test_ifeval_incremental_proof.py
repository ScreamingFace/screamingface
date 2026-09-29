"""Execution proof; production IFEval still uses its existing batch expression."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.aggregation import SelectedCase, finalize_candidate_result
from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import CaseResult, encode_candidate_invocation
from screamingface_engine.benchmarks.ifeval import grade, grading
from screamingface_engine.benchmarks.ifeval.definition import (
    CASE_EVALUATION_ROUTE,
    CHECK_ROUTE,
    REVISION,
)
from screamingface_engine.benchmarks.ifeval.runtime import install
from screamingface_engine.benchmarks.spine.scored import GradeRequest
from url4 import RelExpr, Text, expr, render, src
from url4.peer.server import Request, Url4Node


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    expression = expr(
        src(Text(payload), name="payload", weight=0.0),
        src(
            RelExpr(path=route, context="$payload", intent=Text(intent)), name="result", weight=0.0
        ),
        intent=Text("$result"),
    )
    return (await node.evaluate(render(expression))).text


def _assets(root: Path) -> dict[int, dict[str, Any]]:
    specs = {
        case_id: {
            "key": case_id,
            "prompt": f"Describe tea without commas ({case_id}).",
            "instruction_id_list": ["punctuation:no_comma"],
            "kwargs": [{}],
        }
        for case_id in (1, 2)
    }
    (root / "instructions").mkdir()
    for case_id, spec in specs.items():
        (root / "instructions" / f"{case_id}.json").write_text(json.dumps(spec))
    (root / "cases.json").write_text(
        json.dumps([{"id": key, "input": spec["prompt"]} for key, spec in specs.items()])
    )
    return specs


class _Execution:
    """Test-only early-grade wiring; production keeps its original expression."""

    def __init__(self, root: Path, first_answer: str, monkeypatch: pytest.MonkeyPatch) -> None:
        self.specs = _assets(root)
        path = grade.scored_path(self.specs)
        self.original_grade = path.grade_case
        self.original_check = grading.check_case
        self.checks: list[str] = []
        self.marked: list[int | str] = []
        self.path = replace(path, grade_case=self.counted_grade)
        self.node = Url4Node("test")
        install(self.node, root)
        self.second_started = asyncio.Event()
        self.release_second = asyncio.Event()
        self.first_answer = first_answer
        self.selected = [
            SelectedCase(case_id=key, input=spec["prompt"], metadata={})
            for key, spec in self.specs.items()
        ]
        self.results: list[CaseResult] = []
        self.rows: list[dict[str, object]] = []
        monkeypatch.setattr(grading, "check_case", self.counted_check)
        self.node.endpoint("/proof-candidate")(self.candidate)

    def counted_check(self, **kwargs: Any):
        self.checks.append(kwargs["response"])
        return self.original_check(**kwargs)

    async def counted_grade(self, request: GradeRequest):
        self.marked.append(request.case_id)
        return await self.original_grade(request)

    async def candidate(self, request: Request) -> str:
        if request.intent == "2":
            self.second_started.set()
            await self.release_second.wait()
        answer = self.first_answer if request.intent == "1" else "Fresh tea"
        return encode_candidate_invocation(answer, "stop", None)

    async def execute(self) -> None:
        for case in self.selected:
            invocation = await _call(self.node, "/proof-candidate", "", str(case.case_id))
            record = await _call(self.node, CHECK_ROUTE, invocation, f"{case.case_id}:1")
            evaluation = await _call(
                self.node,
                CASE_EVALUATION_ROUTE,
                json.dumps({"attempt_1": record}),
                str(case.case_id),
            )
            row = case_execution_payload(case.case_id, invocation, [evaluation])
            self.rows.append(row)
            async for result in self.path.iter_case_results(
                json.dumps([row]),
                selected_cases=[case],
                grading_material=lambda case_id: self.specs[case_id],
            ):
                self.results.append(result)

    def assert_final_parity(self) -> None:
        # INVARIANT: finalization consumes grades; it never reruns checking or grading.
        incremental = finalize_candidate_result(
            benchmark_id="ifeval",
            benchmark_revision=REVISION,
            selected_cases=self.selected,
            cases=self.results,
            scorer=grade.score_cases,
        ).as_payload()
        assert self.checks == [self.first_answer, "Fresh tea"]
        assert self.marked == [1, 2]
        batch = grade.aggregate(
            json.dumps(self.rows), self.specs, "ifeval", [1, 2], selected_case_count=2
        )
        assert incremental == batch
        assert self.checks == [self.first_answer, "Fresh tea"]


@pytest.mark.asyncio
@pytest.mark.parametrize("first_answer,first_score", [("Warm tea", 1.0), ("Warm, tea", 0.0)])
async def test_case_grade_precedes_next_answer_and_final_payload_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_answer: str, first_score: float
) -> None:
    execution = _Execution(tmp_path, first_answer, monkeypatch)
    task = asyncio.create_task(execution.execute())
    try:
        await asyncio.wait_for(execution.second_started.wait(), timeout=5)
        assert not task.done()
        assert execution.checks == [first_answer]
        assert execution.marked == [1]
        assert len(execution.results) == 1
        assert grade.score_cases(execution.results).score == first_score
        execution.release_second.set()
        await asyncio.wait_for(task, timeout=5)
    finally:
        execution.release_second.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    execution.assert_final_parity()
