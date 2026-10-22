"""Drive a Benchmark's code mounts the way a run does (spec 2026-10-20 R1).

STORY: as a test author I hand a code mount its named sources — the Case row and the
Attempts, or the collected rows and the selection — and read what it returns, without
re-stating how the Engine composes the run expression.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.protocol import (
    CASE_SOURCE,
    EVALUATIONS_SOURCE,
    SELECTED_SOURCE,
    attempt_source,
)
from url4 import RelUrl, expr, literal, render, src
from url4.peer.server import Url4Node


async def run_code(node: Url4Node, path: str, sources: Mapping[str, str]) -> str:
    """Evaluate ``(name:0.0:'value', …)!path`` on ``node`` and return the result text.

    Every value is inert text: a ``$`` in it is never interpolated.
    """

    expression = expr(
        *(src(literal(value), name=name, weight=0.0) for name, value in sources.items()),
        intent=RelUrl(path),
    )
    result = await node.evaluate(render(expression))
    return result.text


async def run_aggregate(node: Url4Node, path: str, rows: str, selected: int) -> str:
    """The run terminal over ``rows`` (a JSON array of Case rows) for ``selected`` Cases."""

    return await run_code(node, path, {EVALUATIONS_SOURCE: rows, SELECTED_SOURCE: str(selected)})


async def run_case_evaluation(
    node: Url4Node,
    path: str,
    *,
    case: Mapping[str, Any],
    attempts: Sequence[str],
    others: Mapping[str, str] | None = None,
) -> str:
    """The per-Case record over one Case row and its Attempt invocations, in order."""

    sources: dict[str, str] = {CASE_SOURCE: json.dumps(dict(case))}
    sources.update(
        {attempt_source(number): value for number, value in enumerate(attempts, start=1)}
    )
    sources.update(others or {})
    return await run_code(node, path, sources)


def first_grading(row: str) -> Any:
    """The first Attempt's grading outcome of one ``case-execution.v1`` row."""

    return json.loads(row)["grading"][0]


__all__ = [
    "first_grading",
    "run_aggregate",
    "run_case_evaluation",
    "run_code",
]
