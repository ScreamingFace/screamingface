"""Serve and validate public cases before native URL4 selection and execution."""

import json
from collections.abc import Awaitable, Callable

from screamingface_engine.benchmarks.picture_admission import refuse_blind_models
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def install_cases(node: Url4Node, route: str, provider: Callable[[], str]) -> None:
    """Register the existing cases route as a validated collection producer."""
    if route not in node.processor_routes():
        node.endpoint(route)(cases_handler(provider, node=node))


def cases_handler(
    provider: Callable[[], str], *, node: Url4Node | None = None
) -> Callable[[Request], str | Awaitable[str]]:
    def cases(request: Request) -> str | Awaitable[str]:
        raw = provider()
        try:
            rows = json.loads(raw)
            count = int(request.intent)
            if not isinstance(rows, list) or not 1 <= count <= len(rows):
                raise ValueError("invalid selection")
            if any(not isinstance(row, dict) for row in rows[:count]):
                raise ValueError("case rows must be objects")
        except (TypeError, ValueError) as exc:
            raise ResolutionError(
                "Invalid benchmark case selection", code="benchmark_contract_error", permanent=True
            ) from exc
        # FEATURE (OME-1548): the Cases route runs once, before any Candidate call, so it is the
        # last point where a picture run can still refuse a blind model with nothing spent.
        # WHY every row, not rows[:count]: a picture anywhere makes it a picture Benchmark.
        # WHY a coroutine only here: the selection check above stays synchronous, so a bad
        # selection still raises at the call, before anything is awaited.
        if node is not None:
            return _admitted(node, [row for row in rows if isinstance(row, dict)], raw)
        # INVARIANT: validation finishes before inference; URL4 owns slicing and indexing.
        return raw

    return cases


async def _admitted(node: Url4Node, rows: list[dict[str, object]], raw: str) -> str:
    """Serve ``raw`` once the run's Candidate may see this Benchmark's pictures."""
    await refuse_blind_models(node, rows)
    return raw
