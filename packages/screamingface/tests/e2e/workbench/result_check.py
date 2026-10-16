"""Validate a notebook's ``WORKBENCH_RESULT`` payload (e2e workbench spec §3.3).

Pure: the payload and the notebook's declared ``workbench.required_result`` keys in, the
trace ids fit for the chain plus failure reasons out — so it is unit-tested without a stack.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from harness.trace_evidence import TRACE_ID


def check_result(
    result: Mapping[str, Any] | None, required: Sequence[str]
) -> tuple[list[str], list[str]]:
    """(well-formed trace ids, reasons). Only ids matching ``TRACE_ID`` reach the chain."""
    if result is None:
        return [], ["no WORKBENCH_RESULT reported by the notebook"]
    reasons = [f"result lacks declared key {key!r}" for key in required if key not in result]
    raw = result.get("trace_ids", [])
    if not isinstance(raw, list):
        # WHY: a str is iterable — iterating it would check 32 one-character "ids".
        reasons.append(f"trace_ids must be a list of trace ids, got {type(raw).__name__}")
        return [], reasons
    ids: list[str] = []
    for item in raw:  # pyright: ignore[reportUnknownVariableType]
        if isinstance(item, str) and TRACE_ID.fullmatch(item):
            ids.append(item)
        else:
            reasons.append(f"malformed trace id {item!r} (want 32 lowercase hex)")
    if not raw:
        reasons.append("no trace id reported by the notebook")
    return ids, reasons
