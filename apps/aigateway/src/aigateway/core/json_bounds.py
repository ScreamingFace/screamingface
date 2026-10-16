"""Provider-neutral bounds for decoded JSON documents."""

from __future__ import annotations

import math
from typing import Any, Literal

type JsonBoundsReason = Literal["too_deep", "too_many_nodes", "non_finite"]


class JsonBoundsError(ValueError):
    def __init__(self, reason: JsonBoundsReason) -> None:
        super().__init__(reason)
        self.reason = reason


def assert_bounded_json(
    value: Any,
    *,
    max_depth: int,
    max_nodes: int,
    require_finite: bool = False,
) -> None:
    """Reject a decoded JSON tree outside the caller's safety envelope."""

    nodes = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal nodes
        # INVARIANT: check before recursion so hostile JSON cannot move the Python
        # stack beyond the caller's declared depth envelope.
        if depth > max_depth:
            raise JsonBoundsError("too_deep")
        nodes += 1
        if nodes > max_nodes:
            raise JsonBoundsError("too_many_nodes")
        if require_finite and isinstance(node, float) and not math.isfinite(node):
            raise JsonBoundsError("non_finite")
        if isinstance(node, dict):
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)

    walk(value, 0)


__all__ = ["JsonBoundsError", "assert_bounded_json"]
