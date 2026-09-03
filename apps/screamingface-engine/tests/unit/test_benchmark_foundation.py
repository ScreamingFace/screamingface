"""Generic Engine Benchmark discovery and shared-world Candidate Invocation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkInstaller,
    BenchmarkRegistry,
    candidate,
    link_candidate,
)
from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_BINDING,
    CANDIDATE_ROUTE,
    decode_candidate_invocation,
    decode_candidate_invocation_record,
)
from screamingface_engine.config import Settings
from screamingface_engine.model_outcomes import (
    ModelOutcome,
    bind_model_outcome,
    capture_model_outcomes,
    record_model_outcome,
)
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner.web_tools import _is_blocked
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig
from url4 import Node, RelExpr, RelUrl, build, expr, iterate, render, src, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed

pytestmark = pytest.mark.asyncio


def _benchmark(
    *,
    benchmark_id: str = "example-smoke",
    install: BenchmarkInstaller | None = None,
    build_protocol: Callable[[int], Node] | None = None,
) -> Benchmark:
    values = {
        "id": benchmark_id,
        "title": "Example Smoke",
        "description": "One non-comparable structural probe.",
        "revision": "example-smoke-v1",
        "case_count": 3,
        "declaration": BenchmarkDeclaration(
            failure_policy="coverage-declare",
            interaction="single_shot",
        ),
        "build": build_protocol
        or (
            lambda selected: candidate(
                f"Explain why the sky looks blue. Selected cases: {selected}.",
                web_search=False,
            )
        ),
    }
    return Benchmark(**values) if install is None else Benchmark(**values, install=install)


def _link(candidate_expression: Node, benchmark_expression: Node) -> str:
    # The linking convention is published, not re-stated here — a client cannot import a helper
    # that lives in a test file.
    return link_candidate(candidate_expression, benchmark_expression)


async def _get(
    app: FastAPI,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://engine.test",
    ) as client:
        return await client.get(path, headers=headers)


async def test_empty_installation_has_an_honest_empty_catalog() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())
    response = await _get(app, "/v1/benchmarks")

    assert response.status_code == 200
    assert response.json() == {"object": "list", "data": []}


async def test_list_is_complete_metadata_and_detail_is_an_exact_selection() -> None:
    registry = BenchmarkRegistry((_benchmark(),))
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=registry,
    )

    catalog = (await _get(app, "/v1/benchmarks")).json()
    detail = (await _get(app, "/v1/benchmarks/example-smoke?limit=1")).json()

    assert catalog == {
        "object": "list",
        "data": [
            {
                "object": "benchmark",
                "id": "example-smoke",
                "title": "Example Smoke",
                "description": "One non-comparable structural probe.",
                "revision": "example-smoke-v1",
                "case_count": 3,
                # OME-1039: the declared grading contract is part of the public catalog —
                # reviewers approve the policy by reading the manifest, never engine source.
                "failure_policy": "coverage-declare",
                "interaction": "single_shot",
                "href": "/v1/benchmarks/example-smoke",
            }
        ],
    }
    assert detail["schema"] == "screamingface.benchmark.v1"
    assert detail["id"] == "example-smoke"
    assert detail["case_count"] == 3
    assert detail["selected_case_count"] == 1
    assert CANDIDATE_ROUTE in detail["url4"]
    assert "Selected cases: 1" in detail["url4"]


async def test_default_alias_does_not_exist() -> None:
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((_benchmark(),)),
    )

    response = await _get(app, "/v1/benchmarks/default")

    assert response.status_code == 404


async def test_detail_rejects_clamping_and_invalid_limits() -> None:
    benchmark = _benchmark()
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((benchmark,)),
    )

    too_large = await _get(app, "/v1/benchmarks/example-smoke?limit=4")
    empty = await _get(app, "/v1/benchmarks/example-smoke?limit=0")

    assert too_large.status_code == 422
    assert too_large.headers["content-type"].startswith("application/problem+json")
    assert empty.status_code == 422
    for invalid in (True, 0, -1, 4):
        with pytest.raises(ValueError, match="between 1 and 3"):
            benchmark.resource(invalid)  # type: ignore[arg-type]


async def test_detail_supports_entity_specific_conditional_reads() -> None:
    registry = BenchmarkRegistry((_benchmark(),))
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=registry,
    )
    full = await _get(app, "/v1/benchmarks/example-smoke")
    limited = await _get(app, "/v1/benchmarks/example-smoke?limit=1")
    repeated = await _get(
        app,
        "/v1/benchmarks/example-smoke?limit=1",
        headers={"If-None-Match": limited.headers["etag"]},
    )

    assert full.headers["etag"] != limited.headers["etag"]
    assert repeated.status_code == 304
    assert repeated.content == b""


@pytest.mark.parametrize(
    "benchmark_id",
    ("nested:value", "/nested", "nested/benchmark", "nested/", "NESTED"),
)
async def test_benchmark_ids_are_one_flat_lowercase_identifier(benchmark_id: str) -> None:
    with pytest.raises(ValueError, match="one lowercase identifier"):
        _benchmark(benchmark_id=benchmark_id)


async def test_candidate_authoring_canonicalizes_bare_domain_exclusions() -> None:
    protocol = candidate(
        "question",
        web_search=True,
        web_search_exclude=("B.TEST.", "a.test", "b.test"),
    )

    assert "web_search_exclude=a.test:b.test" in render(protocol)
    with pytest.raises(ValueError, match="bare domains"):
        candidate(
            "question",
            web_search=True,
            web_search_exclude="blocked.test",  # type: ignore[arg-type]
        )
    for malformed in (
        ".example.com",
        "bad..example",
        "-bad.example",
        "bad_domain.example",
        "bücher.example",
    ):
        with pytest.raises(ValueError, match="bare domains"):
            candidate("question", web_search=True, web_search_exclude=(malformed,))


async def test_registry_installs_every_concrete_definition_even_with_one_installer() -> None:
    installed: list[Path] = []

    def install(_node: Url4Node, root: Path) -> None:
        installed.append(root)

    registry = BenchmarkRegistry(
        (
            _benchmark(benchmark_id="example-a", install=install),
            _benchmark(benchmark_id="example-b", install=install),
        )
    )
    node = Url4Node("test")
    install_candidate_invocation(node)

    registry.install(node, assets_root=Path("/immutable/assets"))

    assert installed == [Path("/immutable/assets"), Path("/immutable/assets")]


async def test_duplicate_benchmark_routes_fail_installation() -> None:
    def install(node: Url4Node, _root: Path) -> None:
        node.endpoint("/benchmarks/example/private")(lambda _request: "private")

    registry = BenchmarkRegistry(
        (
            _benchmark(benchmark_id="example-a", install=install),
            _benchmark(benchmark_id="example-b", install=install),
        )
    )
    node = Url4Node("test")
    install_candidate_invocation(node)

    with pytest.raises(ValueError, match="already registered"):
        registry.install(node, assets_root=Path("/assets"))


async def test_missing_literal_model_route_fails_before_execution() -> None:
    benchmark = _benchmark(
        build_protocol=lambda _selected: RelExpr(
            path="/judge/missing",
            context="grade",
            intent=text("judge"),
        )
    )
    node = Url4Node("test")
    install_candidate_invocation(node)

    with pytest.raises(ValueError, match="/judge/missing"):
        BenchmarkRegistry((benchmark,)).install(node, assets_root=Path("/assets"))


def _response(requests: list[dict[str, object]]) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "Rayleigh scattering."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    return respond


async def _world(
    registry: BenchmarkRegistry,
    requests: list[dict[str, object]],
    *,
    models: tuple[ModelSpec, ...] = (ModelSpec(id="provider/model"),),
    response: Callable[[httpx.Request], httpx.Response] | None = None,
    tavily_client: httpx.AsyncClient | None = None,
):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(response or _response(requests)),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model="provider/model", models=models),
        client=client,
        tavily_api_key="tvly-test" if tavily_client is not None else None,
        tavily_client=tavily_client,
    )
    install_candidate_invocation(world.node)
    registry.install(world.node, assets_root=Path("/assets"))
    return client, world


async def test_fetched_resource_links_and_executes_through_candidate_route() -> None:
    requests: list[dict[str, object]] = []
    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), requests)
    candidate_expression = RelExpr(
        path="/provider/model",
        context="$input",
        intent=text("Answer accurately."),
    )

    try:
        result = await world.node.evaluate(
            _link(candidate_expression, build(str(benchmark.resource(1)["url4"])))
        )
    finally:
        await world.aclose()
        await client.aclose()

    assert decode_candidate_invocation(result.text) == (
        "Rayleigh scattering.",
        "stop",
        None,
    )
    assert requests == [
        {
            "model": "provider/model",
            "messages": [
                {"role": "system", "content": "Answer accurately."},
                {"role": "user", "content": "Explain why the sky looks blue. Selected cases: 1."},
            ],
        }
    ]


async def test_candidate_uses_the_shared_world_including_benchmark_routes() -> None:
    async def private(_request: Request) -> str:
        return "benchmark-owned value"

    def install(node: Url4Node, _root: Path) -> None:
        node.endpoint("/benchmarks/example/private")(private)

    benchmark = _benchmark(install=install)
    client, world = await _world(BenchmarkRegistry((benchmark,)), [])
    linked = _link(
        RelExpr(
            path="/benchmarks/example/private",
            context="ignored",
            intent=text("read"),
        ),
        benchmark.protocol(1),
    )

    try:
        result = await world.node.evaluate(linked)
    finally:
        await world.aclose()
        await client.aclose()

    assert decode_candidate_invocation(result.text) == ("benchmark-owned value", None, None)


async def test_candidate_preserves_a_successful_empty_output() -> None:
    async def empty(_request: Request) -> str:
        return ""

    def install(node: Url4Node, _root: Path) -> None:
        node.endpoint("/benchmarks/example/empty")(empty)

    benchmark = _benchmark(install=install)
    client, world = await _world(BenchmarkRegistry((benchmark,)), [])
    linked = _link(
        RelExpr(
            path="/benchmarks/example/empty",
            context="ignored",
            intent=text("read"),
        ),
        benchmark.protocol(1),
    )

    try:
        result = await world.node.evaluate(linked)
    finally:
        await world.aclose()
        await client.aclose()

    assert decode_candidate_invocation(result.text) == ("", None, None)


def _candidate_call(
    expression: Node,
    *,
    web_search: bool,
    exclusions: tuple[str, ...] = (),
) -> Node:
    params = [("web_search", "true" if web_search else "false")]
    if exclusions:
        params.append(("web_search_exclude", ":".join(exclusions)))
    call = RelExpr(
        path=CANDIDATE_ROUTE,
        context="question",
        intent=text(render(expression)),
        params=tuple(params),
    )
    return expr(src(call, name="invocation", weight=0.0), intent=text("$invocation"))


async def test_nested_candidate_invocation_is_valid_composition() -> None:
    requests: list[dict[str, object]] = []
    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), requests)
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))
    nested = _candidate_call(_candidate_call(model, web_search=False), web_search=False)

    try:
        outer = await world.node.evaluate(nested)
    finally:
        await world.aclose()
        await client.aclose()

    inner_json, outer_finish, outer_refusal = decode_candidate_invocation(outer.text)
    assert (outer_finish, outer_refusal) == ("stop", None)
    assert decode_candidate_invocation(inner_json) == ("Rayleigh scattering.", "stop", None)
    assert len(requests) == 1


async def test_nested_candidate_cannot_broaden_retrieval_policy() -> None:
    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), [])
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))
    nested = _candidate_call(_candidate_call(model, web_search=True), web_search=False)

    try:
        with pytest.raises(ResolutionError, match="cannot enable retrieval") as caught:
            await world.node.evaluate(nested)
    finally:
        await world.aclose()
        await client.aclose()

    assert caught.value.code == "candidate_policy_escalation"


@pytest.mark.parametrize(
    "params",
    (
        (),
        (("web_search", "yes"),),
        (("web_search", "false"), ("web_search_exclude", "blocked.test")),
        (("web_search", "true"), ("unknown", "value")),
    ),
)
async def test_candidate_policy_is_explicit_and_fail_closed(
    params: tuple[tuple[str, str], ...],
) -> None:
    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), [])
    call = RelExpr(
        path=CANDIDATE_ROUTE,
        context="question",
        intent=text("literal answer"),
        params=params,
    )
    request = expr(src(call, name="invocation", weight=0.0), intent=text("$invocation"))

    try:
        with pytest.raises(ResolutionError) as caught:
            await world.node.evaluate(request)
    finally:
        await world.aclose()
        await client.aclose()

    assert caught.value.code == "candidate_policy_invalid"


async def test_required_retrieval_fails_before_model_spend_when_route_cannot_serve_it() -> None:
    requests: list[dict[str, object]] = []
    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), requests)
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))

    try:
        with pytest.raises(ResolutionError) as caught:
            await world.node.evaluate(_candidate_call(model, web_search=True))
    finally:
        await world.aclose()
        await client.aclose()

    assert caught.value.code == "benchmark_retrieval_unavailable"
    assert requests == []


async def test_required_retrieval_treats_a_blank_tavily_key_as_unconfigured() -> None:
    requests: list[dict[str, object]] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_response(requests)),
        base_url="http://aigateway.test",
    )
    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        base_url="https://api.tavily.com",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/model",
            models=(ModelSpec(id="provider/model"),),
        ),
        client=client,
        tavily_api_key="   ",
        tavily_client=tavily,
    )
    install_candidate_invocation(world.node)
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))

    try:
        with pytest.raises(ResolutionError) as caught:
            await world.node.evaluate(_candidate_call(model, web_search=True))
    finally:
        await world.aclose()
        await client.aclose()
        await tavily.aclose()

    assert caught.value.code == "benchmark_retrieval_unavailable"
    assert requests == []


async def test_retrieval_policy_protects_search_results_and_direct_fetches() -> None:
    model_requests: list[dict] = []

    def model_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model_requests.append(body)
        if len(model_requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "search",
                                        "function": {
                                            "name": "web_search",
                                            "arguments": '{"query":"evidence"}',
                                        },
                                    },
                                    {
                                        "id": "fetch",
                                        "function": {
                                            "name": "web_fetch",
                                            "arguments": '{"url":"https://blocked.test/secret"}',
                                        },
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "researched answer"}, "finish_reason": "stop"}]
            },
        )

    tavily_requests: list[dict] = []

    def tavily_response(request: httpx.Request) -> httpx.Response:
        tavily_requests.append(json.loads(request.content))
        assert request.url.path == "/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "blocked",
                        "url": "https://sub.blocked.test/leak",
                        "content": "secret",
                    },
                    {
                        "title": "idna blocked",
                        "url": "https://bücher.example/leak",
                        "content": "secret",
                    },
                    {
                        "title": "idna-2008 blocked",
                        "url": "https://faß.de/leak",
                        "content": "secret",
                    },
                    {
                        "title": "allowed",
                        "url": "https://allowed.test/source",
                        "content": "public",
                    },
                    {
                        "title": "idna allowed",
                        "url": "https://münchen.example/source",
                        "content": "public idna",
                    },
                ]
            },
        )

    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(tavily_response),
        base_url="https://api.tavily.com",
    )
    benchmark = _benchmark()
    client, world = await _world(
        BenchmarkRegistry((benchmark,)),
        [],
        models=(ModelSpec(id="provider/model"),),
        response=model_response,
        tavily_client=tavily,
    )
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))

    try:
        result = await world.node.evaluate(
            _candidate_call(
                model,
                web_search=True,
                exclusions=("blocked.test", "xn--bcher-kva.example", "xn--fa-hia.de"),
            )
        )
    finally:
        await world.aclose()
        await client.aclose()
        await tavily.aclose()

    assert decode_candidate_invocation(result.text) == ("researched answer", "stop", None)
    assert tavily_requests == [
        {
            "query": "evidence",
            "search_depth": "advanced",
            "max_results": 5,
            "exclude_domains": ["blocked.test", "xn--bcher-kva.example", "xn--fa-hia.de"],
        }
    ]
    tool_messages = [
        message for message in model_requests[1]["messages"] if message["role"] == "tool"
    ]
    assert tool_messages[0]["content"] == (
        "Title: allowed\nURL: https://allowed.test/source\nContent: public\n\n"
        "Title: idna allowed\nURL: https://münchen.example/source\nContent: public idna"
    )
    assert "blocked by Benchmark retrieval policy" in tool_messages[1]["content"]


async def test_provider_refusal_is_a_normal_candidate_envelope() -> None:
    def refusal(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": None, "refusal": "safety policy"},
                        "finish_reason": "content_filter",
                    }
                ]
            },
        )

    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), [], response=refusal)
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))

    try:
        result = await world.node.evaluate(_candidate_call(model, web_search=False))
    finally:
        await world.aclose()
        await client.aclose()

    assert decode_candidate_invocation(result.text) == (
        "",
        "content_filter",
        "safety policy",
    )


async def test_a_null_text_refusal_still_publishes_as_a_refusal() -> None:
    """A provider refusal remains typed even when the provider supplied no refusal text."""

    def refusal(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": None, "refusal": None},
                        "finish_reason": "content_filter",
                    }
                ]
            },
        )

    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), [], response=refusal)
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))

    try:
        result = await world.node.evaluate(_candidate_call(model, web_search=False))
    finally:
        await world.aclose()
        await client.aclose()

    invocation = decode_candidate_invocation_record(result.text)
    assert invocation.status == "refused"
    assert decode_candidate_invocation(result.text) == ("", "content_filter", None)


async def test_provider_refusal_uses_its_own_outcome_when_a_sibling_finishes_later() -> None:
    node = Url4Node("test")
    install_candidate_invocation(node)

    async def refuse(_request: Request) -> str:
        record_model_outcome("content_filter", "safety policy")
        record_model_outcome("content_filter", "different sibling policy")
        raise bind_model_outcome(
            ResolutionError(
                "provider refused the request",
                code="provider_refusal",
                permanent=True,
            ),
            ModelOutcome("content_filter", "safety policy"),
        )

    node.endpoint("/provider/refuse")(refuse)
    expression = RelExpr(path="/provider/refuse", context="$input", intent=text("answer"))

    result = await node.evaluate(_candidate_call(expression, web_search=False))

    assert decode_candidate_invocation(result.text) == (
        "",
        "content_filter",
        "safety policy",
    )


async def test_model_outcome_capture_is_task_local_and_nested() -> None:
    both_started = asyncio.Event()
    started = 0

    async def capture(reason: str) -> tuple[str | None, list[str | None]]:
        nonlocal started
        with capture_model_outcomes() as outer:
            with capture_model_outcomes() as inner:
                record_model_outcome(reason, None)
                started += 1
                if started == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=1)
            return inner[-1].finish_reason, [item.finish_reason for item in outer]

    first, second = await asyncio.gather(capture("stop"), capture("length"))

    assert first == ("stop", ["stop"])
    assert second == ("length", ["length"])


async def test_runner_composition_installs_benchmarks_with_the_injected_asset_root() -> None:
    roots: list[Path] = []

    def install(_node: Url4Node, root: Path) -> None:
        roots.append(root)

    benchmark = _benchmark(install=install)
    registry = BenchmarkRegistry((benchmark,))
    requests: list[dict[str, object]] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_response(requests)),
        base_url="http://aigateway.test",
    )
    config = WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model="provider/model",
            models=(ModelSpec(id="provider/model"),),
        )
    )
    model = RelExpr(path="/provider/model", context="$input", intent=text("answer"))
    executor = build_executor(
        {},
        config,
        client=client,
        benchmarks=registry,
        benchmark_assets_root=Path("/immutable/assets"),
    )

    try:
        frames = [frame async for frame in executor.execute(_link(model, benchmark.protocol(1)))]
    finally:
        await client.aclose()

    assert roots == [Path("/immutable/assets")]
    assert isinstance(frames[-1], Completed)
    assert frames[-1].result.body is not None
    assert decode_candidate_invocation(frames[-1].result.body) == (
        "Rayleigh scattering.",
        "stop",
        None,
    )


async def _two_branch_candidate(
    fast_outcome: ModelOutcome,
    slow_outcome: ModelOutcome,
) -> tuple[str, str | None, str | None]:
    """Run one Candidate whose scope records two outcomes, returning the FAST branch's text."""

    # An explicit default processor: without one the node falls back to the FIRST registered
    # endpoint, which would make the Candidate adapter itself reduce the group.
    node = Url4Node("test", default_processor="/provider/fast")
    install_candidate_invocation(node)

    async def fast(_request: Request) -> str:
        record_model_outcome(fast_outcome.finish_reason, fast_outcome.refusal)
        return "fast answer"

    async def slow(_request: Request) -> str:
        # Finishes LAST, so a "most recent outcome" rule would attribute this branch's
        # terminal fields to the answer produced by `fast`.
        await asyncio.sleep(0.01)
        record_model_outcome(slow_outcome.finish_reason, slow_outcome.refusal)
        return "slow answer"

    node.endpoint("/provider/fast")(fast)
    node.endpoint("/provider/slow")(slow)

    branches = expr(
        src(
            RelExpr(path="/provider/fast", context="$input", intent=text("a")),
            name="a",
            weight=0.0,
        ),
        src(
            RelExpr(path="/provider/slow", context="$input", intent=text("b")),
            name="b",
            weight=0.0,
        ),
        # A pure structural reference: the answer is `fast`'s text and no further model call
        # is made to produce it.
        intent=text("$a"),
    )

    result = await node.evaluate(_candidate_call(branches, web_search=False))
    return decode_candidate_invocation(result.text)


async def test_divergent_sibling_outcomes_are_reported_as_unknown() -> None:
    """A sibling's terminal fields are never attributed to another branch's answer."""

    output, finish_reason, refusal = await _two_branch_candidate(
        ModelOutcome("stop", None),
        ModelOutcome("length", None),
    )

    assert output == "fast answer"
    assert finish_reason is None
    assert refusal is None


async def test_a_tolerated_sibling_refusal_never_accompanies_an_answer() -> None:
    """The contract has no shape for a non-empty output carrying a provider refusal."""

    output, finish_reason, refusal = await _two_branch_candidate(
        ModelOutcome("stop", None),
        ModelOutcome("content_filter", "safety policy"),
    )

    assert output == "fast answer"
    assert refusal is None
    assert finish_reason is None


async def test_agreeing_sibling_outcomes_are_still_reported() -> None:
    """Unanimity is not ambiguity — an agreed outcome still describes the answer."""

    output, finish_reason, refusal = await _two_branch_candidate(
        ModelOutcome("stop", None),
        ModelOutcome("stop", None),
    )

    assert output == "fast answer"
    assert finish_reason == "stop"
    assert refusal is None


@pytest.mark.parametrize(
    "url",
    [
        "https://ev%69l.com/page",
        "https://evil%2ecom/page",
        "https://sub.ev%69l.com/page",
    ],
)
async def test_percent_encoded_hosts_cannot_evade_an_exclusion(url: str) -> None:
    """httpx leaves the authority percent-encoded; a fetcher downstream may not."""

    assert _is_blocked(url, ("evil.com",)) is True


async def test_missing_relative_source_route_fails_before_execution() -> None:
    """A `(/cases)` data reference names a route just as a `/path!intent` call does."""

    benchmark = _benchmark(
        build_protocol=lambda _selected: expr(
            src(RelUrl("/cases/missing"), name="cases", weight=0.0),
            intent=text("summarize"),
        )
    )
    node = Url4Node("test")
    install_candidate_invocation(node)

    with pytest.raises(ValueError, match="/cases/missing"):
        BenchmarkRegistry((benchmark,)).install(node, assets_root=Path("/assets"))


async def test_a_benchmark_may_serve_its_cases_from_a_data_route() -> None:
    """`data()` routes are servable relative targets, so referencing one is not a missing route."""

    def install(node: Url4Node, _root: Path) -> None:
        node.data("/cases/example", '[{"id": "c1"}]', media_type="application/json")

    benchmark = _benchmark(
        install=install,
        build_protocol=lambda _selected: expr(
            src(RelUrl("/cases/example"), name="cases", weight=0.0),
            intent=text("summarize"),
        ),
    )
    node = Url4Node("test")
    install_candidate_invocation(node)

    BenchmarkRegistry((benchmark,)).install(node, assets_root=Path("/assets"))


async def test_iteration_templates_do_not_invent_routes_from_placeholders() -> None:
    """A row template names no route until `$item` is substituted, so it cannot be validated."""

    def build_protocol(_selected: int) -> Node:
        return iterate(
            RelUrl("/cases/example"),
            "(/judge/$item)!'grade'",
            intent="'grade'",
        )

    def install(node: Url4Node, _root: Path) -> None:
        node.data("/cases/example", '[{"id": "c1"}]', media_type="application/json")

    node = Url4Node("test")
    install_candidate_invocation(node)

    BenchmarkRegistry((_benchmark(install=install, build_protocol=build_protocol),)).install(
        node, assets_root=Path("/assets")
    )


async def test_detail_resource_publishes_the_candidate_binding() -> None:
    """A client cannot link a Candidate it must learn the name of from a test helper."""

    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((_benchmark(),)),
    )

    detail = (await _get(app, "/v1/benchmarks/example-smoke")).json()

    assert detail["candidate_binding"] == CANDIDATE_BINDING
    assert f"${CANDIDATE_BINDING}" in detail["url4"]


async def test_the_published_linking_helper_executes_a_fetched_resource() -> None:
    """`link_candidate` is the one definition of how a Candidate is bound to a protocol."""

    requests: list[dict[str, object]] = []
    benchmark = _benchmark()
    client, world = await _world(BenchmarkRegistry((benchmark,)), requests)
    candidate_expression = RelExpr(path="/provider/model", context="$input", intent=text("answer"))

    protocol = benchmark.resource()["url4"]
    assert isinstance(protocol, str)

    try:
        # Exactly what a client holds after a fetch: the resource's URL4 text, nothing else.
        result = await world.node.evaluate(link_candidate(candidate_expression, protocol))
    finally:
        await world.aclose()
        await client.aclose()

    assert "Rayleigh scattering." in result.text
