"""Peak-memory benchmark for large fetched collections (a measurement, not a test).

Run from the package root::

    uv run python scripts/bench_collection_memory.py [--mb 50]

Two scenarios, both under :mod:`tracemalloc` (Python-heap bytes, not RSS):

1. ``iterate``: a ``--mb``-sized declared-JSON ``FetchedText`` body of base64-like rows
   (trailing newline, like a file read off disk) handed to ``MapNode._items`` with
   ``;iteration.slice=0:2`` — the path a ``cases*(…)`` iteration over two rows takes. The
   body is allocated BEFORE tracing starts, so the peak is what parsing adds on top of it.
2. ``memo``: a hand-built graph ``big -> consume -> later`` where ``later`` runs after
   ``big``'s only consumer finished; reports the traced bytes still alive at ``later``.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import time
import tracemalloc
from collections.abc import Mapping

from url4 import StaticIOLayer
from url4.core.nodes import IterationDirectives
from url4.dag import ExecutionContext, Payload, run
from url4.dag.node import DagNode
from url4.dag.nodes import MapNode
from url4.dag.nodes._shared import FetchedText

_MB = 1024 * 1024


def _body(total_mb: int, rows: int = 181) -> FetchedText:
    per_row = total_mb * _MB // rows
    blob = "QUJD" * (per_row // 4)
    data = [{"id": i, "score": 2.50, "image": blob} for i in range(rows)]
    return FetchedText(json.dumps(data) + "\n", "application/json")


def bench_iterate(total_mb: int) -> None:
    body = _body(total_mb)
    node = MapNode(body="$item", directives=IterationDirectives(slice=(0, 2)))
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    items = node._items(body)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    body_mb = len(body) / _MB
    print(
        f"iterate: body {body_mb:.1f} MiB, rows kept {len(items)}, "
        f"peak added {peak / _MB:.1f} MiB ({peak / len(body):.2f}x body), {elapsed:.2f}s"
    )


class _Node:
    def __init__(self, name: str, deps: dict[str, DagNode], fn) -> None:
        self.name = name
        self._deps = deps
        self._fn = fn

    @property
    def deps(self) -> Mapping[str, DagNode]:
        return self._deps

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return self._fn(inputs)


def bench_memo(total_mb: int) -> None:
    seen: dict[str, int] = {}

    def at_later(_inputs: Mapping[str, Payload]) -> str:
        gc.collect()
        seen["alive"] = tracemalloc.get_traced_memory()[0]
        return "done"

    big = _Node("big", {}, lambda _i: ["x" * (total_mb * _MB)])
    consume = _Node("consume", {"in": big}, lambda i: str(len(i["in"][0])))
    later = _Node("later", {"after": consume}, at_later)
    tracemalloc.start()
    asyncio.run(run(later, StaticIOLayer({})))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"memo: result {total_mb} MiB, still alive at later stage "
        f"{seen['alive'] / _MB:.1f} MiB, run peak {peak / _MB:.1f} MiB"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mb", type=int, default=50, help="synthetic body size in MiB")
    args = parser.parse_args()
    bench_iterate(args.mb)
    bench_memo(args.mb)


if __name__ == "__main__":
    main()
