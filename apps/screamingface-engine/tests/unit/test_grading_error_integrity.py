"""Grading failures reach the Case Result as the ORIGINAL upstream error (OME-924).

Before this fix, a failed judge branch inside a Benchmark's inner model-grading fan-out
was collected (url4's default ``on_error="collect"``) into the criterion/rubric row list,
where the case-evaluation route decoded the error object as a typed grading record and
masked the real failure with "invalid Criterion envelope". These tests pin the two halves
of the repair:

- the inner fan-outs (DRACO criteria, HealthBench rubric items) now fail fast, so the
  original error propagates to the shared ``preserve_candidate_outcome()`` boundary
  instead of being collected as a malformed grading record;
- url4's collect payload carries the exception's own ``code`` and ``retryable`` beside
  kind/message, so ``public_error`` renders the upstream failure instead of the default.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.draco import aggregate as draco_agg
from screamingface_engine.benchmarks.draco import prepare
from screamingface_engine.benchmarks.draco.definition import DRACO
from screamingface_engine.benchmarks.draco.exam import (
    JUDGE_MODEL,
    build_draco_protocol,
)
from screamingface_engine.benchmarks.draco.exam import (
    Routes as DracoRoutes,
)
from screamingface_engine.benchmarks.healthbench import aggregate as healthbench_agg
from screamingface_engine.benchmarks.healthbench.exam import (
    Routes as HealthRoutes,
)
from screamingface_engine.benchmarks.healthbench.exam import (
    build_exam_protocol,
)
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.runner.connector import (
    AigatewayConfig,
    AigatewayWorld,
    build_aigateway_world,
)
from screamingface_engine.world_config import ModelSpec
from url4 import RelExpr, render, text

pytestmark = pytest.mark.asyncio

_RUBRIC = {
    "sections": [
        {"id": "Factual Accuracy", "criteria": [{"id": "a1", "weight": 2, "requirement": "x"}]}
    ]
}

_CANDIDATE_MODEL = "openrouter/deepseek/deepseek-v4-pro"


# --- the protocol fan-outs fail fast ---------------------------------------------------


async def test_draco_inner_grading_fanout_fails_fast() -> None:
    routes = DracoRoutes.for_exam("draco", "0123456789abcdef")
    rendered = render(build_draco_protocol(routes, case_count=1, judge_passes=5))
    # Exactly ONE explicit fail-fast policy: the inner criterion fan-out. The outer Case
    # fan-out and the preserve_candidate_outcome boundary keep the collect default, which
    # renders nothing (collect IS the default).
    assert rendered.count(";iteration.on_error=fail") == 1


async def test_healthbench_inner_grading_fanout_fails_fast() -> None:
    routes = HealthRoutes.for_exam("healthbench-worst30", "0123456789abcdef")
    rendered = render(build_exam_protocol(routes, case_count=1, available_case_count=1))
    assert rendered.count(";iteration.on_error=fail") == 1


# --- the aggregate renders the original error, not an envelope failure ------------------


def _execution(case_id: int, answer: str, grading: object) -> dict[str, object]:
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [grading],
    )


def _error_row(
    *,
    kind: str = "ResolutionError",
    code: str | None = None,
    message: str = "upstream judge rate limited",
    retryable: bool | None = None,
    permanent: bool | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {"kind": kind, "message": message}
    if code is not None:
        error["code"] = code
    if retryable is not None:
        error["retryable"] = retryable
    if permanent is not None:
        error["permanent"] = permanent
    return {"error": error}


async def test_draco_grading_error_preserves_code_and_retryable() -> None:
    rows = json.dumps(
        [
            _execution(
                1,
                "the candidate answer",
                _error_row(code="rate_limited", retryable=True),
            )
        ]
    )
    result = draco_agg.aggregate(
        rows,
        {1: _RUBRIC},
        "draco",
        selected_cases=[{"id": 1, "input": "Question 1"}],
        judge_passes=5,
    )

    (case,) = result["cases"]
    assert case["status"] == "failed"
    assert case["output"] == "the candidate answer"
    assert case["grade"]["score"] is None
    (failure,) = case["failures"]
    assert failure == {
        "stage": "grading",
        "code": "rate_limited",
        "message": "upstream judge rate limited",
        "retryable": True,
        "case_id": 1,
        "metadata": {"error_kind": "ResolutionError"},
    }
    assert "Criterion envelope" not in failure["message"]


async def test_draco_grading_failure_keeps_a_permanent_classification() -> None:
    result = draco_agg.aggregate(
        json.dumps(
            [
                _execution(
                    1,
                    "the candidate answer",
                    _error_row(code="aigateway_bad_response", permanent=True),
                )
            ]
        ),
        {1: _RUBRIC},
        "draco",
        selected_cases=[{"id": 1, "input": "Question 1"}],
        judge_passes=5,
    )

    (case,) = result["cases"]
    (failure,) = case["failures"]
    assert failure["code"] == "aigateway_bad_response"
    assert failure["retryable"] is False


async def test_draco_grading_failure_without_code_falls_back_to_the_default() -> None:
    # A legacy collect payload (kind + message only) still renders, with the benchmark's
    # declared default code — backward compatible with pre-OME-924 error rows.
    result = draco_agg.aggregate(
        json.dumps([_execution(1, "the candidate answer", _error_row())]),
        {1: _RUBRIC},
        "draco",
        selected_cases=[{"id": 1, "input": "Question 1"}],
        judge_passes=5,
    )

    (case,) = result["cases"]
    (failure,) = case["failures"]
    assert failure["stage"] == "grading"
    assert failure["code"] == "draco_grading_failed"
    assert failure["retryable"] is None
    assert failure["message"] == "upstream judge rate limited"


def _write_healthbench_case(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "cases.json").write_text(json.dumps([{"id": 1, "input": "input-1"}]), encoding="utf-8")


async def test_healthbench_grading_error_preserves_code_and_retryable(tmp_path: Path) -> None:
    _write_healthbench_case(tmp_path)
    rows = json.dumps(
        [
            _execution(
                1,
                "the candidate answer",
                _error_row(code="rate_limited", retryable=True),
            )
        ]
    )
    result = healthbench_agg.aggregate(
        rows,
        tmp_path,
        benchmark_id="healthbench-test",
        benchmark_revision="revision",
        case_ids=(1,),
        mean=sum,
    )

    (case,) = result["cases"]
    assert case["status"] == "failed"
    assert case["output"] == "the candidate answer"
    assert case["grade"]["score"] is None
    (failure,) = case["failures"]
    assert failure["stage"] == "grading"
    assert failure["code"] == "rate_limited"
    assert failure["retryable"] is True
    assert failure["metadata"] == {"error_kind": "ResolutionError"}


# --- end to end: a real judge 429 through the full DRACO protocol -----------------------


def _draco_assets(root: Path) -> Path:
    bundle = root / "draco"
    prepare.build(
        [
            {"problem": f"Question {index}", "answer": json.dumps(_RUBRIC), "domain": "finance"}
            for index in range(1, 101)
        ],
        bundle,
    )
    return root


def _tavily(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"results": [{"title": "s", "url": "https://allowed.test/x", "content": "public"}]},
    )


async def _judge_429_world(
    tmp_path: Path,
) -> tuple[
    httpx.AsyncClient,
    httpx.AsyncClient,
    AigatewayWorld,
    list[dict[str, object]],
]:
    """A full DRACO world whose judge route answers 429 and candidates answer fine."""
    requests: list[dict[str, object]] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("model") == JUDGE_MODEL:
            return httpx.Response(
                429,
                json={
                    "detail": {
                        "code": "rate_limited",
                        "message": "upstream judge rate limited",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "A fine answer."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway),
        base_url="http://aigateway.test",
    )
    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(_tavily),
        base_url="https://api.tavily.com",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=_CANDIDATE_MODEL,
            models=(ModelSpec(id=_CANDIDATE_MODEL), ModelSpec(id=JUDGE_MODEL)),
        ),
        client=client,
        tavily_api_key="tvly-test",
        tavily_client=tavily,
    )
    install_candidate_invocation(world.node)
    BenchmarkRegistry((DRACO,)).install(world.node, assets_root=_draco_assets(tmp_path))
    return client, tavily, world, requests


async def test_a_judge_429_lands_as_the_original_grading_error(tmp_path: Path) -> None:
    """Judge calls 429, the candidate answers fine — the case failure carries the upstream
    code/message/retryability, never an envelope mask."""
    client, tavily, world, requests = await _judge_429_world(tmp_path)
    candidate_expression = RelExpr(
        path=f"/{_CANDIDATE_MODEL}",
        context="$input",
        intent=text("Answer the question."),
    )
    linked = link_candidate(candidate_expression, DRACO.build(1))
    try:
        result = await world.node.evaluate(linked)
    finally:
        await world.aclose()
        await client.aclose()
        await tavily.aclose()

    candidate = CandidateResult.model_validate(json.loads(result.text))
    (case,) = candidate.cases
    assert case.output == "A fine answer."
    assert case.grade is not None
    assert case.grade.score is None
    (failure,) = case.failures
    assert failure.stage == "grading"
    assert failure.code == "rate_limited"
    assert failure.retryable is True
    assert "upstream judge rate limited" in failure.message
    assert "Criterion envelope" not in failure.message
    # Every judge pass was paid as a real 429 — no masking swallowed them.
    judge_calls = [body for body in requests if body.get("model") == JUDGE_MODEL]
    assert judge_calls, "the judge must actually have been called"
