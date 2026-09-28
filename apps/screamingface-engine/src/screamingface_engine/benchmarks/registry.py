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
from url4.core.parser import split_top_level_commas
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
            missing = sorted(_relative_endpoint_paths(protocol) - declared)
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
    pending = [protocol]
    while pending:
        selected = pending.pop()
        for child in walk(selected):
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
            pending.extend(_embedded_protocols(child))
    return found


def _embedded_protocols(node: Node) -> Iterator[Node]:
    templates: tuple[str | None, ...] = ()
    if isinstance(node, Iteration):
        templates = (node.body, node.intent, node.reducer)
    elif isinstance(node, RelExpr) and node.context and "@" not in node.context:
        # INVARIANT: local call contexts execute source lists, including the selector's
        # dataset. Holdings contexts stay opaque in URL4; remote contexts execute elsewhere.
        # WHY empty intent: build() requires a complete expression around a source list.
        # This wrapper is inspected only, never evaluated or published.
        # URL4 ignores empty source slots (for example a trailing comma) before parsing.
        context = ",".join(filter(str.strip, split_top_level_commas(node.context)))
        templates = (f"({context})!''",)
    for template in templates:
        if not template:
            continue
        try:
            yield build(template)
        except ParseError:
            # WHY: unresolved iteration templates and free-prose contexts may be legal at
            # runtime without being parseable here; do not invent routes from that text.
            continue


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
