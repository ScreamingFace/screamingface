"""Candidate compilation and one-fetch Benchmark linkage contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from _model_parameter_fixtures import details as _model_details
from url4 import RelExpr, build, expr, iterate, render, src, text

import screamingface as sf
from screamingface import _surface as sx
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.benchmark import _decode_benchmark_resource
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.compilation import compile_evaluation
from screamingface._evaluation.linking import link_candidate
from screamingface._evaluation.model import Candidate


def _benchmark_url4() -> str:
    return render(
        expr(
            src(
                RelExpr(
                    path="/candidate",
                    context="A question with commas, (parentheses), and $variables.",
                    intent=text("$candidate"),
                ),
                name="answer",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path="/provider/judge",
                    context="$answer",
                    intent=text("Grade the answer."),
                ),
                name="grade",
                weight=0.0,
            ),
            intent=text("$grade"),
        )
    )


def _resource(*, url4: str | None = None) -> dict[str, object]:
    return {
        "schema": "screamingface.benchmark.v1",
        "id": "bench-1",
        "title": "Fixture Benchmark",
        "description": "A deterministic fixture.",
        "revision": "fixture-revision",
        "case_count": 3,
        "url4": _benchmark_url4() if url4 is None else url4,
    }


def test_benchmark_resource_is_data_plus_one_ordinary_url4_expression() -> None:
    benchmark = _decode_benchmark_resource(
        _resource(),
        requested_id="bench-1",
        requested_limit=1,
    )

    assert benchmark.info.id == "bench-1"
    assert benchmark.info.case_count == 3
    assert benchmark.case_count == 1
    assert benchmark.info.revision == "fixture-revision"
    assert render(build(benchmark.url4)) == benchmark.url4
    assert not hasattr(benchmark, "protocol")
    assert not hasattr(benchmark, "plan_route")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "other"}, "schema"),
        ({"id": "other"}, "wrong Benchmark id"),
        ({"revision": ""}, "revision"),
        ({"url4": "not valid ("}, "URL4"),
    ],
)
def test_benchmark_resource_contract_is_validated(
    change: dict[str, object],
    message: str,
) -> None:
    payload = {**_resource(), **change}

    with pytest.raises(sf.PlanningError, match=message):
        _decode_benchmark_resource(
            payload,
            requested_id="bench-1",
            requested_limit=1,
        )


@pytest.mark.parametrize(
    ("response", "code", "permanent", "message"),
    [
        (
            httpx.Response(422, json={"detail": "limit exceeds the installed cases"}),
            "invalid_benchmark_selection",
            True,
            "limit exceeds the installed cases",
        ),
        (
            httpx.Response(503, json=[]),
            "benchmark_fetch_failed",
            False,
            "Could not fetch the Benchmark expression",
        ),
    ],
)
def test_benchmark_resource_http_failures_are_typed(
    response: httpx.Response,
    code: str,
    permanent: bool,
    message: str,
) -> None:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(lambda _: response),
    ) as client:
        with pytest.raises(sf.PlanningError, match=message) as exc_info:
            client.evaluate(sf.Model("provider/model"), benchmark="bench-1")

    assert exc_info.value.code == code
    assert exc_info.value.status == response.status_code
    assert exc_info.value.permanent is permanent


def test_model_compilation_uses_candidate_owned_defaults_and_input_binding() -> None:
    compiled = compile_candidate(sf.Model("provider/model"))

    assert compiled.kind == "model"
    assert compiled.models == ("provider/model",)
    assert compiled.url4 is not None
    assert "$input" in compiled.url4
    assert "Answer the request accurately and completely." in compiled.url4
    assert "Follow every instruction and formatting constraint" in compiled.url4
    assert "reasoning=" not in compiled.url4
    assert "max_tokens=" not in compiled.url4
    assert "web_search=" not in compiled.url4
    assert [operation.kind for operation in compiled.operations] == ["model"]


def test_fusion_compilation_is_benchmark_agnostic_and_uses_explicit_policy() -> None:
    compiled = compile_candidate(
        sx.Fanout(
            [
                sf.Model("provider/a", prompt="Answer from A."),
                sf.Model("provider/b"),
            ],
            name="pair",
        )
        >> sx.Synthesize("provider/synth"),
    )

    assert compiled.kind == "fusion"
    assert compiled.models == (
        "provider/a",
        "provider/b",
        "provider/synth",
    )
    assert compiled.url4 is not None
    assert "/provider/a" in compiled.url4
    assert "/provider/b" in compiled.url4
    assert "/provider/synth" in compiled.url4
    assert "Answer from A." in compiled.url4
    assert "Synthesize the strongest supported answer" in compiled.url4
    assert "follow every instruction and formatting constraint" in compiled.url4
    assert [operation.kind for operation in compiled.operations] == [
        "model",
        "model",
        "synthesis",
    ]
    assert [member.name for member in compiled.members] == ["a", "b"]


def test_linker_preserves_a_top_level_benchmark_iteration_without_templates() -> None:
    candidate = compile_candidate(sf.Model("provider/model"))
    benchmark = render(
        iterate(
            ("one", "two"),
            body=src(
                RelExpr(
                    path="/candidate",
                    context="$item",
                    intent=text("$candidate"),
                ),
                name="answer",
                weight=0.0,
            ),
            intent=text("$answer"),
            on_error="fail",
        )
    )

    linked = link_candidate(candidate.url4, benchmark).url4

    assert render(build(linked)) == linked
    assert linked.count("/provider/model") == 1
    assert "/candidate" in linked
    assert "$input" in linked


def test_evaluation_inspection_combines_benchmark_and_candidate_requirements() -> None:
    benchmark = _decode_benchmark_resource(
        _resource(),
        requested_id="bench-1",
        requested_limit=1,
    )
    recipes = (
        sf.Model("provider/a"),
        sx.Fanout([sf.Model("provider/a"), sf.Model("provider/b")], name="pair")
        >> sx.Synthesize("provider/synth"),
    )

    evaluation = compile_evaluation(
        recipes,
        benchmark,
        1,
    )

    assert evaluation.required_models == (
        "provider/a",
        "provider/b",
        "provider/synth",
    )
    assert [operation.kind for operation in evaluation.candidates[0].operations] == ["model"]
    assert [operation.kind for operation in evaluation.candidates[1].operations] == [
        "model",
        "model",
        "synthesis",
    ]


def _structural_resource() -> dict[str, object]:
    return _resource(url4="(member:0.0:/validate($candidate_member_1)!'$member')!'$member'")


def test_structural_candidate_bindings_are_rejected_before_model_preflight() -> None:
    requests: list[str] = []

    def engine(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/benchmarks/bench-1":
            return httpx.Response(200, json=_structural_resource())
        if request.url.path == "/v1/models":
            return httpx.Response(503, json={"detail": "catalog unavailable"})
        raise AssertionError(f"unexpected Engine request: {request.method} {request.url}")

    fusion = sx.Fanout(
        [sf.Model("provider/a"), sf.Model("provider/b")], name="pair"
    ) >> sx.Synthesize("provider/synth")
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine),
    ) as client:
        with pytest.raises(sf.PlanningError, match="unsupported structural Candidate") as error:
            client.evaluate(fusion, benchmark="bench-1")

    assert error.value.code == "candidate_shape_mismatch"
    assert requests == ["/v1/benchmarks/bench-1"]


@pytest.mark.asyncio
async def test_async_structural_candidate_bindings_are_rejected_before_model_preflight() -> None:
    requests: list[str] = []

    def engine(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/benchmarks/bench-1":
            return httpx.Response(200, json=_structural_resource())
        if request.url.path == "/v1/models":
            return httpx.Response(503, json={"detail": "catalog unavailable"})
        raise AssertionError(f"unexpected Engine request: {request.method} {request.url}")

    fusion = sx.Fanout(
        [sf.Model("provider/a"), sf.Model("provider/b")], name="pair"
    ) >> sx.Synthesize("provider/synth")
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine),
    ) as client:
        with pytest.raises(sf.PlanningError, match="unsupported structural Candidate") as error:
            await client.evaluate(fusion, benchmark="bench-1")

    assert error.value.code == "candidate_shape_mismatch"
    assert requests == ["/v1/benchmarks/bench-1"]


class _Transport:
    def __init__(self) -> None:
        self.candidates: list[Candidate] = []

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        self.candidates.append(candidate)
        return _RunOutcome(
            run_id=f"run_{candidate.name}",
            started_at=datetime(2026, 8, 1, tzinfo=UTC),
            completed_at=datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC),
            result_body=json.dumps(
                {
                    "schema": "screamingface.candidate-result.v1",
                    "benchmark_id": "bench-1",
                    "benchmark_revision": "fixture-revision",
                    "case_count": 1,
                    "score": 0.8,
                    "coverage": 1.0,
                    "metrics": {},
                    "cases": [
                        {
                            "status": "scored",
                            "case_id": 1,
                            "input": "Question",
                            "output": "Answer",
                            "finish_reason": "stop",
                            "refusal": None,
                            "stop_reason": None,
                            "rounds_executed": None,
                            "grade": {
                                "method": "fixture",
                                "score": 0.8,
                                "metrics": {},
                                "checks": [],
                            },
                            "failures": [],
                            "metadata": {},
                        }
                    ],
                    "failures": [],
                }
            ),
            media_type="application/json",
            root_usage=None,
        )

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_client_fetches_once_then_locally_builds_every_candidate_url4() -> None:
    benchmark_requests: list[httpx.Request] = []

    def engine(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/benchmarks/bench-1":
            benchmark_requests.append(request)
            return httpx.Response(200, json=_resource())
        if request.method == "GET" and request.url.path == "/v1/models":
            models = (
                "provider/a",
                "provider/b",
                "provider/synth",
                "provider/judge",
            )
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": model,
                            "object": "model",
                            "owned_by": model.split("/", 1)[0],
                            "supported_parameters": [],
                            "supported_tools": [],
                            "unsupported_parameter_behavior": "reject",
                            "parameter_contract_url": f"/v1/model-parameters?model={model}",
                        }
                        for model in models
                    ],
                },
            )
        if request.method == "GET" and request.url.path == "/v1/model-parameters":
            return httpx.Response(200, json=_model_details(request.url.params["model"]))
        raise AssertionError(f"unexpected Engine request: {request.method} {request.url}")

    candidates = [
        sf.Model("provider/a", prompt="Custom answer prompt."),
        sx.Fanout([sf.Model("provider/a"), sf.Model("provider/b")], name="pair")
        >> sx.Synthesize("provider/synth"),
    ]
    transport = _Transport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine),
        run_transport=transport,
    ) as client:
        report = client.evaluate(candidates, benchmark="bench-1", limit=1)

    assert [candidate.name for candidate in report.candidates] == ["a", "pair"]
    # One Candidate-independent Benchmark fetch is shared by every Candidate.
    assert len(benchmark_requests) == 1
    assert "members" not in str(benchmark_requests[0].url)
    assert dict(benchmark_requests[0].url.params) == {"limit": "1"}
    assert len(transport.candidates) == 2
    for candidate in transport.candidates:
        assert render(build(candidate.url4)) == candidate.url4
        assert "/candidate" in candidate.url4
        assert "/provider/judge" in candidate.url4
    assert transport.candidates[0].url4.count("/provider/a") == 1
    assert transport.candidates[1].url4.count("/provider/a") == 1
    assert transport.candidates[1].url4.count("/provider/b") == 1
