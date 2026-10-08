"""Run-scoped tally of a frozen-copy run (capture or replay), shared by connectors and the executor.

FEATURE: OME-1307 — a capture run records, for every chat call and every web-tool result, whether
the gateway stored it in the frozen copy; a replay run counts the answers it already received per
request, so the gateway can serve identical requests in capture order.

A shared leaf: stdlib only, importable by both halves of the engine.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["capture", "replay"]
Lane = Literal["chat", "tool"]
Status = Literal["stored", "failed", "refused", "missing", "error"]
Reason = Literal["failed", "refused", "missing", "open", "seal", "error"]

_REASONS: tuple[Reason, ...] = ("failed", "refused", "missing", "open", "seal", "error")
_FROZEN_COPY_ID = "capture.frozen_copy_id"
_STATUS = "capture.status"
_REPLAY = "capture.replay"
_PARTIAL_PREFIX = "capture.partial."


@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    """What one chat call or one tool result says about whether the copy holds it."""

    lane: Lane
    status: Status
    digest: str | None = None
    """:func:`request_digest` of the request, so a retry can be told from a different call."""


# The two ways the gateway tells a replay that it cannot answer (design §4.4). Engine-authored
# codes with a fixed message each: nothing of the gateway's text is carried.
REPLAY_MISS = "frozen_copy_miss"
REPLAY_UNAVAILABLE = "frozen_copy_unavailable"


def replay_refusal_code(status: int, payload: object) -> str | None:
    """The replay code a gateway response states, or ``None`` when it is not a replay refusal.

    Only a 404 can be one. ``detail.code`` names it. A 404 whose ``detail`` is exactly the
    framework's own "Not Found" is a gateway without the replay routes (design §9, older than B1):
    the copy cannot be served, so it reads as unavailable. Any other 404 is a captured error.
    """
    if status != 404 or not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if detail == "Not Found":
        return REPLAY_UNAVAILABLE
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if code in (REPLAY_MISS, REPLAY_UNAVAILABLE) else None


def _reason_of(status: Status) -> Reason:
    """The partial reason a non-stored status counts under (``stored`` never reaches here)."""
    return "error" if status in ("stored", "error") else status


def request_digest(payload: Mapping[str, object]) -> str:
    """sha256 of the canonical JSON of a request: the identity of one logical call."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CaptureTally:
    """One run's frozen-copy state. Mutable and owned by one run."""

    mode: Mode | None = None
    """``None`` for a normal run. Set by the executor that honoured the run's header."""
    frozen_copy_id: str | None = None
    """Capture: the copy the run opened (``None`` while closed or when the open failed).
    Replay: the copy the run replays."""
    open_failed: bool = False
    """The copy could not be opened: the run went on uncaptured."""
    seal_failed: bool = False
    """The copy could not be sealed: a replay refuses an open copy."""
    outcomes: list[CaptureOutcome] = field(default_factory=list)
    answers: dict[tuple[Lane, str], int] = field(default_factory=dict)

    def status(self) -> Literal["complete", "partial"]:
        """``complete`` only for a capture run whose copy opened and sealed and whose every call
        is stored. An empty run is complete: it has nothing a replay could miss."""
        complete = (
            self.mode == "capture"
            and not self.open_failed
            and not self.seal_failed
            and not self._lost()
        )
        return "complete" if complete else "partial"

    def attributes(self) -> dict[str, str | int]:
        """The run's frozen-copy state as run-summary attributes. Empty for a normal run.

        A replay run states only the copy it replays: that is the proof the engine honoured the
        header. A capture run states its copy, its status and a count per partial reason (zeros
        omitted). It never carries a request digest or any request content.
        """
        if self.mode == "replay" and self.frozen_copy_id is not None:
            return {_REPLAY: self.frozen_copy_id}
        if self.mode != "capture":
            return {}
        attributes: dict[str, str | int] = {}
        if self.frozen_copy_id is not None:
            attributes[_FROZEN_COPY_ID] = self.frozen_copy_id
        attributes[_STATUS] = self.status()
        counts: dict[Reason, int] = {reason: 0 for reason in _REASONS}
        for outcome in self._lost():
            counts[_reason_of(outcome.status)] += 1
        counts["open"] += self.open_failed
        counts["seal"] += self.seal_failed
        for reason in _REASONS:
            if counts[reason]:
                attributes[f"{_PARTIAL_PREFIX}{reason}"] = counts[reason]
        return attributes

    def _lost(self) -> list[CaptureOutcome]:
        """The outcomes that are not stored, less each error that a later stored call of the same
        request made up for: only the final attempt of a logical call counts (D2)."""
        served: set[str] = set()
        lost: list[CaptureOutcome] = []
        for outcome in reversed(self.outcomes):
            if outcome.status == "stored":
                if outcome.digest is not None:
                    served.add(outcome.digest)
            elif outcome.status != "error" or outcome.digest not in served:
                lost.append(outcome)
        return lost

    def occurrence(self, lane: Lane, digest: str) -> int:
        """How many successful answers this run already received for this request."""
        return self.answers.get((lane, digest), 0)

    def answered(self, lane: Lane, digest: str) -> None:
        """Count one more successful answer for this request."""
        self.answers[(lane, digest)] = self.occurrence(lane, digest) + 1


_tally: contextvars.ContextVar[CaptureTally | None] = contextvars.ContextVar(
    "screamingface_engine_capture_tally", default=None
)


@contextmanager
def capture_outcomes() -> Iterator[CaptureTally]:
    """Bind a fresh tally for this scope; restore the previous binding on exit."""

    tally = CaptureTally()
    token = _tally.set(tally)
    try:
        yield tally
    finally:
        _tally.reset(token)


def current_capture_tally() -> CaptureTally | None:
    """The tally bound for this task, or ``None`` outside a run that keeps one."""

    return _tally.get()


def record_capture_outcome(outcome: CaptureOutcome) -> None:
    """Append one outcome to the bound tally. A no-op when none is bound."""

    tally = _tally.get()
    if tally is not None:
        tally.outcomes.append(outcome)


__all__ = [
    "REPLAY_MISS",
    "REPLAY_UNAVAILABLE",
    "CaptureOutcome",
    "CaptureTally",
    "capture_outcomes",
    "current_capture_tally",
    "record_capture_outcome",
    "replay_refusal_code",
    "request_digest",
]
