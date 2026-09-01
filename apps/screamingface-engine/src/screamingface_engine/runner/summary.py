"""The process-level summary one run leaves behind (OME-1069).

The run's telemetry lives in the CloudEvents stream; this is the small, exact
record the run mode logs to its own process output so an operator reading a Job's
logs gets the one-stop answer — outcome, duration, cost, cache, overflow — without
correlating the stream by hand. Exact-only, like the rest of the run's accounting:
``cost_usd`` is the subtree total or ``None`` (unpriced/unknown), never a false
zero, and cache counters are present only when the run completed, because a failed
run's counters are partial and must not read as exact.

Deliberately a leaf with no engine imports: both ``runner.executor`` (which
computes the data) and ``runner.operation_capture`` (which delegates the accessor)
import it without dragging the url4 engine into the latter's import graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

RunOutcome = Literal["succeeded", "failed", "stopped"]


@dataclass(frozen=True, slots=True)
class RunSummary:
    """What one run's process-level telemetry can state, exactly or not at all."""

    outcome: RunOutcome
    trace_id: str | None
    error_code: str | None = None
    error_type: str | None = None
    duration_s: float | None = None
    cost_usd: Decimal | None = None
    pricing_version: str | None = None
    cache_attributes: Mapping[str, str | int | float | bool | None] | None = None
    dropped_logs: int | None = None
    high_water: int | None = None


__all__ = ["RunOutcome", "RunSummary"]
