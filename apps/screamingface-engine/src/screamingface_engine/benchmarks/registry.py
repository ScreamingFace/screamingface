"""Validated registry shared by Benchmark discovery and Runner installation."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType

from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.expression_routes import relative_route_paths
from url4 import render
from url4.peer.server import Url4Node

BENCHMARK_ASSETS_ENV = "URL4_BENCHMARK_ASSETS"
DEFAULT_BENCHMARK_ASSETS_ROOT = Path("/opt/benchmarks")


def assets_root(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the immutable asset root once at the Runner composition boundary."""

    selected = os.environ if env is None else env
    return Path(selected.get(BENCHMARK_ASSETS_ENV) or DEFAULT_BENCHMARK_ASSETS_ROOT)


class BenchmarkRegistry:
    """One immutable set of Benchmarks installed on an Engine deployment."""

    __slots__ = ("_benchmarks",)

    def __init__(self, benchmarks: Iterable[Benchmark] = ()) -> None:
        selected: dict[str, Benchmark] = {}
        for benchmark in benchmarks:
            if benchmark.id in selected:
                raise ValueError(f"duplicate Benchmark id {benchmark.id!r}")
            selected[benchmark.id] = benchmark
        self._benchmarks: Mapping[str, Benchmark] = MappingProxyType(selected)

    def __len__(self) -> int:
        return len(self._benchmarks)

    def __iter__(self) -> Iterator[Benchmark]:
        for benchmark_id in sorted(self._benchmarks):
            yield self._benchmarks[benchmark_id]

    def get(self, benchmark_id: str) -> Benchmark | None:
        return self._benchmarks.get(benchmark_id)

    def install(self, node: Url4Node, *, assets_root: Path) -> None:
        """Install and validate every concrete protocol before its first paid request."""

        for benchmark in self:
            benchmark.install(node, assets_root)
        declared = served_routes(node)
        for benchmark in self:
            protocol = benchmark.protocol(benchmark.case_count)
            # Rendering at installation catches malformed hand-built ASTs before discovery can
            # publish an expression that the Runner cannot execute.
            render(protocol)
            missing = sorted(relative_route_paths(protocol, as_executed=False) - declared)
            if missing:
                raise ValueError(
                    f"Benchmark {benchmark.id!r} references uninstalled endpoint(s) {missing}"
                )


def served_routes(node: Url4Node) -> frozenset[str]:
    """Every URL path ``node`` serves directly: its endpoints and its data routes.

    FX-55 / B3 review R8: the ONE accessor for this union. `world.serving.node_mount_paths` (the
    collision guard), `world.factory.build_world` (the direct-mount route set it captures before
    Benchmarks install) and :meth:`BenchmarkRegistry.install` (the endpoint check) all call it,
    so none of the three can disagree about what a node serves. It lives here, not in
    `world`: `benchmarks` is a shared leaf (`.claude/scripts/check_layering.py`) that the world
    may import and that may not import the world.
    """

    return frozenset(node.processor_routes()) | data_routes(node)


def data_routes(node: Url4Node) -> frozenset[str]:
    """The node's data paths, which are servable relative targets too.

    WHY read privately: `processor_routes()` lists endpoints only, and `Url4Node` publishes no
    accessor for its data table — widening the engine's API is outside this landing's boundary.
    Degrades to the endpoint-only check rather than rejecting a valid Benchmark.
    """

    return frozenset(getattr(node, "_data", {}))


EMPTY_BENCHMARKS = BenchmarkRegistry()

__all__ = [
    "BENCHMARK_ASSETS_ENV",
    "DEFAULT_BENCHMARK_ASSETS_ROOT",
    "BenchmarkRegistry",
    "EMPTY_BENCHMARKS",
    "assets_root",
    "data_routes",
    "served_routes",
]
