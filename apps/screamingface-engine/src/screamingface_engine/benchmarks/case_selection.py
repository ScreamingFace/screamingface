"""Selected dataset order is authoritative for human-facing case positions."""

import json

from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

SELECTION_ROUTE = "/benchmarks/selected-cases"


def install_case_selection(node: Url4Node) -> None:
    if SELECTION_ROUTE not in node.processor_routes():
        node.endpoint(SELECTION_ROUTE)(_select)


def _select(request: Request) -> str:
    try:
        rows = json.loads(request.context)
        count = int(request.intent)
        if not isinstance(rows, list) or not 1 <= count <= len(rows):
            raise ValueError("invalid selection")
        selected = rows[:count]
        if any(not isinstance(row, dict) for row in selected):
            raise ValueError("case rows must be objects")
        # INVARIANT: telemetry metadata is separate from each row's original input.
        return json.dumps(
            [
                {**row, "_sf_case_position": index, "_sf_case_count": count}
                for index, row in enumerate(selected, 1)
            ]
        )
    except (TypeError, ValueError) as exc:
        raise ResolutionError(
            "Invalid benchmark case selection", code="benchmark_contract_error", permanent=True
        ) from exc
