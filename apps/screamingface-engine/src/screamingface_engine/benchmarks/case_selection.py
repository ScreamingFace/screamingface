"""Serve and validate public cases before native URL4 selection and execution."""

import json
from collections.abc import Callable

from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def install_cases(node: Url4Node, route: str, provider: Callable[[], str]) -> None:
    """Register the existing cases route as a validated collection producer."""
    if route not in node.processor_routes():
        node.endpoint(route)(cases_handler(provider))


def cases_handler(provider: Callable[[], str]) -> Callable[[Request], str]:
    def cases(request: Request) -> str:
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
        # INVARIANT: validation finishes before inference; URL4 owns slicing and indexing.
        return raw

    return cases
