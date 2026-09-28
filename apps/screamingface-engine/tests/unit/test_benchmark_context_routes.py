"""Registry validation follows executable local contexts, never literal model input."""

from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.definition import Benchmark, BenchmarkDeclaration
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from url4 import Node, RelExpr, RemoteExpr, Text, render
from url4.peer.server import Url4Node


def _benchmark(protocol: Node) -> Benchmark:
    return Benchmark(
        id="context-routes",
        title="Context routes",
        description="Registration dependency validation.",
        revision="v1",
        case_count=1,
        declaration=BenchmarkDeclaration(
            failure_policy="coverage_declare", interaction="single_shot", difficulty="medium"
        ),
        build=lambda _count: protocol,
    )


def _selection_protocol() -> Node:
    return build_evaluation_protocol(
        cases_route="/cases/example",
        case_evaluation=Text("answer"),
        selected_case_count=1,
        available_case_count=1,
        aggregate_route="/aggregate",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("registered", [False, True])
async def test_cases_dataset_is_validated_before_evaluation(registered: bool) -> None:
    # INVARIANT: the cases processor must remain visible to registry validation.
    node = Url4Node("context-routes")
    node.endpoint("/aggregate")(lambda request: request.context)
    protocol = _selection_protocol()
    if registered:
        install_cases(node, "/cases/example", lambda: '[{"id": "first"}]')
    try:
        registry = BenchmarkRegistry((_benchmark(protocol),))
        if not registered:
            with pytest.raises(ValueError, match="/cases/example"):
                registry.install(node, assets_root=Path("/unused"))
        else:
            registry.install(node, assets_root=Path("/unused"))
            assert (await node.evaluate(render(protocol))).text == '["answer"]'
    finally:
        await node.aclose()


@pytest.mark.asyncio
async def test_remote_context_routes_are_not_local_dependencies() -> None:
    node = Url4Node("context-routes")
    protocol = RemoteExpr(
        authority="remote.example", path="/consume", context="/remote-data", intent=Text("")
    )
    try:
        BenchmarkRegistry((_benchmark(protocol),)).install(node, assets_root=Path("/unused"))
    finally:
        await node.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        "/missing",
        "'/literal', /missing",
        "/nested(/missing)!'read'",
        "/missing, prose",
        "/missing,",
        ", /missing",
    ],
)
async def test_local_context_dependencies_are_checked_recursively(context: str) -> None:
    node = Url4Node("context-routes")
    node.endpoint("/consume")(lambda request: request.context)
    node.endpoint("/nested")(lambda request: request.context)
    protocol = RelExpr(path="/consume", context=context, intent=Text(""))
    try:
        with pytest.raises(ValueError, match="/missing"):
            BenchmarkRegistry((_benchmark(protocol),)).install(node, assets_root=Path("/unused"))
    finally:
        await node.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    ["'/missing'", "Please read /missing", "@, /missing"],
)
async def test_literal_and_runtime_fallback_contexts_are_not_dependencies(context: str) -> None:
    # WHY: URL4 treats an unparseable source list or a holdings context as opaque text.
    node = Url4Node("context-routes")
    node.endpoint("/consume")(lambda request: request.context)
    protocol = RelExpr(path="/consume", context=context, intent=Text(""))
    try:
        BenchmarkRegistry((_benchmark(protocol),)).install(node, assets_root=Path("/unused"))
        assert (await node.evaluate(render(protocol))).text
    finally:
        await node.aclose()
