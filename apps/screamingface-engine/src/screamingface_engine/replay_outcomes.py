"""The run's cache-version outcomes, reported by the world and tallied by the run (E14, RP-13)."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, Protocol

VersionOutcome = Literal["hit", "miss"]
GrantRejectionReason = Literal[
    "signature", "expired", "audience", "unknown_version", "subject", "unknown"
]
_GRANT_REJECTION_REASONS: dict[str, GrantRejectionReason] = {
    "signature": "signature",
    "expired": "expired",
    "audience": "audience",
    "unknown_version": "unknown_version",
    "subject": "subject",
}
# WHY a lookup and not a membership test: pyright keeps the Literal through `.get`, the same idiom
# as `world/cache_readback.py` (`_LEGACY_STATUSES`). The set is the closed CV-E4 reason set.


def grant_rejection_reason(raw: object) -> GrantRejectionReason:
    """The closed CV-E4 reason, or "unknown" for anything else. Never raises."""
    return _GRANT_REJECTION_REASONS.get(raw, "unknown") if isinstance(raw, str) else "unknown"


class ReplayOutcomeSink(Protocol):
    def record_version(self, outcome: VersionOutcome, key: str | None) -> None: ...
    def record_grant_rejection(self, reason: GrantRejectionReason) -> None: ...


_sink: contextvars.ContextVar[ReplayOutcomeSink | None] = contextvars.ContextVar(
    "screamingface_engine_replay_outcome_sink", default=None
)


@contextmanager
def replay_outcome_scope(sink: ReplayOutcomeSink | None) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def report_version_outcome(outcome: VersionOutcome, key: str | None) -> None:
    """No-op when no run bound a sink (the sync surface, a bare test)."""
    sink = _sink.get()
    if sink is not None:
        sink.record_version(outcome, key)


def report_grant_rejection(reason: GrantRejectionReason) -> None:
    sink = _sink.get()
    if sink is not None:
        sink.record_grant_rejection(reason)
