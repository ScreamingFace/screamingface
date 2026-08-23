"""Validated registry shared by Benchmark discovery and Runner installation."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType

from screamingface_engine.benchmarks.definition import Benchmark
from url4 import Iteration, Node, RelExpr, RelUrl, build, render
from url4.core.errors import ParseError
from url4.core.nodes import walk
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
        declared = frozenset(node.processor_routes()) | _data_routes(node)
        for benchmark in self:
            protocol = benchmark.protocol(benchmark.case_count)
            # Rendering at installation catches malformed hand-built ASTs before discovery can
            # publish an expression that the Runner cannot execute.
            render(protocol)
            missing = sorted(_relative_endpoint_paths(protocol) - declared)
            if missing:
                raise ValueError(
                    f"Benchmark {benchmark.id!r} references uninstalled endpoint(s) {missing}"
                )


def _data_routes(node: Url4Node) -> frozenset[str]:
    """The node's data paths, which are servable relative targets too.

    WHY read privately: `processor_routes()` lists endpoints only, and `Url4Node` publishes no
    accessor for its data table — widening the engine's API is outside this landing's boundary.
    Degrades to the endpoint-only check rather than rejecting a valid Benchmark.
    """

    return frozenset(getattr(node, "_data", {}))


# A path is only a route name while every segment is literal. url4's segment charset is
# ALPHA / DIGIT / "-" / "_" / "." / "~" (spec §8), and a reference may carry a call, a query or
# parameters after it — `!/reduce()` and `(/cases?limit=2)` both name the route before that tail.
_LITERAL_PATH = re.compile(r"/[A-Za-z0-9\-_.~]+(?:/[A-Za-z0-9\-_.~]+)*")
_PATH_TAILS = frozenset({"", "(", ")", "?", "#", ";", "!", ","})


def _literal_path(reference: str) -> str | None:
    """The route a relative reference names, or None when it names none until substitution."""

    match = _LITERAL_PATH.match(reference.strip())
    if match is None:
        return None
    # `/judge/$item` matches only as far as `/judge`, and `/judge` is not the route it will
    # resolve to. A reference whose tail continues the path is unvalidatable, not broken.
    return match.group() if reference.strip()[match.end() :][:1] in _PATH_TAILS else None


def _relative_endpoint_paths(protocol: Node) -> set[str]:
    """Collect literal relative routes, including those inside iteration templates."""

    found: set[str] = set()
    for child in walk_benchmark_expression(protocol):
        # A `/path!intent` call and a bare `(/path)` data reference both resolve against the
        # routes installed on this node, so both have to be checked.
        reference = (
            child.path
            if isinstance(child, RelExpr)
            else child.value
            if isinstance(child, RelUrl)
            else None
        )
        if reference is not None and (path := _literal_path(reference)) is not None:
            found.add(path)
    return found


def walk_benchmark_expression(protocol: Node) -> Iterator[Node]:
    """Walk structural children and parseable URL4 held in Iteration templates."""

    pending = [protocol]
    while pending:
        selected = pending.pop()
        for child in walk(selected):
            yield child
            if isinstance(child, Iteration):
                # WHY body+intent together: this is the exact expression MapNode spawns for one
                # row. A named body source is not necessarily parseable on its own, so walking the
                # strings separately silently misses legal routes inside the template.
                row_expression = (
                    f"({child.body})!{child.intent}" if child.intent else f"({child.body})"
                )
                # The per-row intent is also a processor target in its own right. In the combined
                # expression it is represented as RelUrl text, while standalone parsing exposes
                # an embedded call's context and intent for discovery.
                for template in (row_expression, child.intent, child.reducer):
                    if not template:
                        continue
                    try:
                        pending.append(build(template))
                    except ParseError:
                        # A row template is URL4 only once `$item` is substituted, so one that
                        # cannot be parsed here carries no route to check. Skipping narrows the
                        # check; raising would fail the world for a legal Benchmark.
                        continue


EMPTY_BENCHMARKS = BenchmarkRegistry()

__all__ = [
    "BENCHMARK_ASSETS_ENV",
    "DEFAULT_BENCHMARK_ASSETS_ROOT",
    "BenchmarkRegistry",
    "EMPTY_BENCHMARKS",
    "assets_root",
    "walk_benchmark_expression",
]
