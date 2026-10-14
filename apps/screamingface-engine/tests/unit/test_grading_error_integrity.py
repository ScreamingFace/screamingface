"""Grading failures reach the Case Result as the ORIGINAL upstream error (OME-924).

Before this fix, a failed judge branch inside a Benchmark's inner model-grading fan-out
was collected (url4's default ``on_error="collect"``) into the criterion/rubric row list,
where the case-evaluation route decoded the error object as a typed grading record and
masked the real failure with "invalid Criterion envelope". These tests pin the two halves
of the repair:

- the inner fan-out (HealthBench rubric items; DRACO's criteria too, until OME-1527 moved it
  to a local inspect Task) now fails fast, so the
  original error propagates to the shared ``preserve_candidate_outcome()`` boundary
  instead of being collected as a malformed grading record;
- url4's collect payload carries the exception's own ``code`` and ``retryable`` beside
  kind/message, so ``public_error`` renders the upstream failure instead of the default.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import httpx
import pytest

# WHY imported: the e2e half below needs a prepared HealthBench answer key, and this is the
# writer its own runtime tests use.
from test_healthbench_dual_benchmark_runtime import _write_full_assets  # noqa: E402

from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload
from screamingface_engine.benchmarks.healthbench import grade as healthbench_agg
from screamingface_engine.benchmarks.healthbench.definition import HEALTHBENCH_WORST30
from screamingface_engine.benchmarks.healthbench.revision_inputs import JUDGE_MODEL
from screamingface_engine.benchmarks.healthbench.variant import (
    Routes as HealthRoutes,
)
from screamingface_engine.benchmarks.healthbench.variant import (
    build_variant_protocol,
)
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import (
    AigatewayConfig,
    AigatewayWorld,
    build_aigateway_world,
)
from url4 import RelExpr, render, text

pytestmark = pytest.mark.asyncio

_CANDIDATE_MODEL = "openrouter/deepseek/deepseek-v4-pro"


# --- the protocol fan-outs fail fast ---------------------------------------------------


async def test_healthbench_inner_grading_fanout_fails_fast() -> None:
    routes = HealthRoutes.for_variant("healthbench-worst30", "0123456789abcdef")
    rendered = render(build_variant_protocol(routes, case_count=1, available_case_count=1))
    # Exactly ONE explicit fail-fast policy: the inner rubric fan-out. The outer Case
    # fan-out and the preserve_candidate_outcome boundary keep the collect default, which
    # renders nothing (collect IS the default).
    assert rendered.count(";iteration.on_error=fail") == 1


# --- the aggregate renders the original error, not an envelope failure ------------------


def _execution(case_id: int, answer: str, grading: object) -> dict[str, object]:
    return graded_answer_payload(
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


def _healthbench_failure(tmp_path: Path, grading: object) -> dict[str, object]:
    """Aggregate one HealthBench Case whose grading collected ``grading``; its one Failure."""

    _write_healthbench_case(tmp_path)
    result = healthbench_agg.aggregate(
        json.dumps([_execution(1, "the candidate answer", grading)]),
        tmp_path,
        benchmark_id="healthbench-test",
        benchmark_revision="revision",
        case_ids=(1,),
        mean=sum,
    )
    (case,) = result["cases"]
    (failure,) = case["failures"]
    return failure


async def test_a_grading_failure_keeps_a_permanent_classification(tmp_path: Path) -> None:
    # Moved from DRACO's aggregate (OME-1527): the same shared `public_error` rendering.
    failure = _healthbench_failure(
        tmp_path, _error_row(code="aigateway_bad_response", permanent=True)
    )

    assert failure["code"] == "aigateway_bad_response"
    assert failure["retryable"] is False


async def test_a_grading_failure_without_code_falls_back_to_the_default(tmp_path: Path) -> None:
    # A legacy collect payload (kind + message only) still renders, with the benchmark's
    # declared default code — backward compatible with pre-OME-924 error cases.
    failure = _healthbench_failure(tmp_path, _error_row())

    assert failure["stage"] == "grading"
    assert failure["code"] == "healthbench_grading_failed"
    assert failure["retryable"] is None
    assert failure["message"] == "upstream judge rate limited"


# --- end to end: a real judge 429 through the full HealthBench protocol ------------------


def _healthbench_assets(root: Path) -> Path:
    # WHY HealthBench (OME-1527): DRACO was this suite's full-protocol subject until it moved to
    # a local inspect Task; HealthBench is the hand-built judged Benchmark left.
    _write_full_assets(root / "healthbench")
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
    """A full HealthBench world whose judge route answers 429 and candidates answer fine."""
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
    BenchmarkRegistry((HEALTHBENCH_WORST30,)).install(
        world.node, assets_root=_healthbench_assets(tmp_path)
    )
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
    linked = link_candidate(candidate_expression, HEALTHBENCH_WORST30.build(1))
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


async def _judge_transport_world(
    tmp_path: Path,
    *,
    fail_first_judge_posts: int | None = None,
) -> tuple[
    httpx.AsyncClient,
    httpx.AsyncClient,
    AigatewayWorld,
    list[dict[str, object]],
]:
    """A full HealthBench world whose judge route raises httpx.ReadError; candidates answer fine.

    ``fail_first_judge_posts``: raise ReadError for the first N judge POSTs, then answer
    with a valid verdict. None → always raise for judge POSTs.
    """
    requests: list[dict[str, object]] = []
    judge_posts = 0

    def gateway(request: httpx.Request) -> httpx.Response:
        nonlocal judge_posts
        body = json.loads(request.content)
        requests.append(body)
        if body.get("model") == JUDGE_MODEL:
            if fail_first_judge_posts is None or judge_posts < fail_first_judge_posts:
                judge_posts += 1
                raise httpx.ReadError("")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"explanation": "evidence", "criteria_met": True}
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
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
    BenchmarkRegistry((HEALTHBENCH_WORST30,)).install(
        world.node, assets_root=_healthbench_assets(tmp_path)
    )
    return client, tavily, world, requests


async def test_a_judge_transport_error_is_retried_and_the_case_is_graded(
    tmp_path: Path,
) -> None:
    """A transient judge transport failure is retried (connector backoff) and the case is graded.

    WHY (OME-1016): the connector retries ``httpx.TransportError`` with backoff, so a
    stale keep-alive connection or a brief aigateway blip costs one extra attempt instead
    of a failed Case.
    """
    client, tavily, world, requests = await _judge_transport_world(
        tmp_path, fail_first_judge_posts=1
    )
    candidate_expression = RelExpr(
        path=f"/{_CANDIDATE_MODEL}",
        context="$input",
        intent=text("Answer the question."),
    )
    linked = link_candidate(candidate_expression, HEALTHBENCH_WORST30.build(1))
    try:
        with (
            mock.patch("screamingface_engine.world.connector._TRANSPORT_BACKOFF_BASE_S", 0.0),
            mock.patch("screamingface_engine.world.connector._TRANSPORT_BACKOFF_MAX_S", 0.0),
            mock.patch("screamingface_engine.world.connector._TRANSPORT_BACKOFF_JITTER_S", 0.0),
        ):
            result = await world.node.evaluate(linked)
    finally:
        await world.aclose()
        await client.aclose()
        await tavily.aclose()

    candidate = CandidateResult.model_validate(json.loads(result.text))
    (case,) = candidate.cases
    assert case.failures == []
    assert case.grade is not None
    assert case.grade.score is not None
    # The first judge call consumed the single transport failure across its retry.
    judge_calls = [body for body in requests if body.get("model") == JUDGE_MODEL]
    assert len(judge_calls) >= 2


async def test_a_judge_transport_error_exhaustion_lands_as_aigateway_transport_error(
    tmp_path: Path,
) -> None:
    """Judge transport failures exhaust retries — the case failure names the real cause.

    WHY (OME-1016): after the connector's bounded retries, the failure must render as
    ``aigateway_transport_error`` with ``retryable=true`` and a non-empty message —
    never the opaque ``healthbench_grading_failed`` fallback.
    """
    client, tavily, world, requests = await _judge_transport_world(tmp_path)
    candidate_expression = RelExpr(
        path=f"/{_CANDIDATE_MODEL}",
        context="$input",
        intent=text("Answer the question."),
    )
    linked = link_candidate(candidate_expression, HEALTHBENCH_WORST30.build(1))
    try:
        with (
            mock.patch("screamingface_engine.world.connector._TRANSPORT_BACKOFF_BASE_S", 0.0),
            mock.patch("screamingface_engine.world.connector._TRANSPORT_BACKOFF_MAX_S", 0.0),
            mock.patch("screamingface_engine.world.connector._TRANSPORT_BACKOFF_JITTER_S", 0.0),
        ):
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
    assert failure.code == "aigateway_transport_error"
    assert failure.retryable is True
    assert "ReadError" in failure.message
    assert "Criterion envelope" not in failure.message
    judge_calls = [body for body in requests if body.get("model") == JUDGE_MODEL]
    assert judge_calls, "the judge must actually have been called"
