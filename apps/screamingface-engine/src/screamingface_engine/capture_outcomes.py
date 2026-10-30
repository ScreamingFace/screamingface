"""Run-scoped tally of a frozen-copy run (capture or replay), shared by connectors and the executor.

FEATURE: OME-1307 — a capture run records, for every chat call and every web-tool result, whether
the gateway stored it in the frozen copy. Each logical call takes an occurrence of its case key and
request, in capture and in replay, so a replay reads the exact entry its capture stored (§5.4).

FEATURE: OME-1775 — a no-answer outcome in a Case that failed does not make the run partial, because
a replay fails that Case again (spec §4, R1). The tally keeps each Case's final result for it.

A shared leaf: stdlib only, importable by both halves of the engine.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["capture", "replay"]
Lane = Literal["chat", "tool"]
Status = Literal["stored", "failed", "refused", "missing", "error", "ambiguous"]

_REASONS = ("failed", "refused", "missing", "open", "seal", "error", "ambiguous", "local")
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
    """:func:`request_digest` of the request the call sent."""
    case_id: str | None = None
    """``str()`` of the call's Case id (OME-1775); ``None`` when the call names no Case."""
    case_key: str = ""
    """The call's case key (:func:`case_key_for`); ``""`` when the call names no Case."""
    occurrence: int | None = None
    """The occurrence the call took (:meth:`CaptureTally.next_occurrence`)."""
    answered: bool = True
    """The model got an answer: a chat call's 2xx response was read, or a tool call gave one."""


# The gateway's frozen-copy contract (design §4): the names both ends of a call share, kept in ONE
# place so the connector and the web tools can never half-rename one.
FROZEN_COPY_HEADER = "X-AIGW-Frozen-Copy"
CAPTURE_FIELD = "X-AIGW-Capture"
REPLAY_FIELD = "X-AIGW-Replay"
"""The replay answer of a found entry: ``hit`` or ``error`` (design §4.4). A non-2xx replay answer
without it is one the copy did not serve (design §5.3 item 2a)."""
CASE_KEY_HEADER = "X-AIGW-Case-Key"
"""The call's case key (design §5.4). Sent only when it is not empty: absent means ``""``."""
CALL_OCCURRENCE_HEADER = "X-AIGW-Call-Occurrence"
"""The call's occurrence, in decimal. Always sent (design §5.4)."""
FROZEN_COPIES_PATH = "/v1/frozen-copies"


def seal_path(copy_id: str) -> str:
    return f"{FROZEN_COPIES_PATH}/{copy_id}/seal"


def replay_chat_path(copy_id: str) -> str:
    return f"{FROZEN_COPIES_PATH}/{copy_id}/chat/completions"


def tool_results_path(copy_id: str) -> str:
    return f"{FROZEN_COPIES_PATH}/{copy_id}/tool-results"


def tool_lookup_path(copy_id: str) -> str:
    return f"{FROZEN_COPIES_PATH}/{copy_id}/tool-results/lookup"


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


def request_digest(payload: Mapping[str, object]) -> str:
    """sha256 of the canonical JSON of a request: the identity of one logical call."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def call_key_headers(case_key: str, occurrence: int) -> dict[str, str]:
    """The call-key headers of one logical call (design §5.4). The case-key header is omitted when
    the key is empty: absence means ``""``."""
    headers = {CALL_OCCURRENCE_HEADER: str(occurrence)}
    if case_key:
        headers[CASE_KEY_HEADER] = case_key
    return headers


def case_key_for(case_id: object, attempt: int) -> str:
    """The case key of one Attempt of one Case (design §5.4): 32 lowercase hex characters.

    The id keeps its type in the key: the integer 1 and the string "1" name different Cases.
    """
    seed = json.dumps(["case", case_id, attempt], separators=(",", ":"))
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


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
    sealed: bool = False
    """The gateway confirmed the seal. A replay refuses an open copy, so only a sealed copy can
    make a capture run complete."""
    local: bool = False
    """A capture on the local runtime (Q23). A local capture is never reproducible: the local app
    may point at the hosted gateway, so the run is never complete."""
    outcomes: list[CaptureOutcome] = field(default_factory=list)
    occurrences: dict[tuple[str, Lane, str], int] = field(default_factory=dict)
    """Per (case key, lane, request digest), the occurrence the next logical call takes."""
    case_results: dict[str, bool] = field(default_factory=dict)
    """Per str(Case id), True when a replay may score the Case: ANY final Case result of the run
    scored it, or failed on time (OME-1775 R1, `benchmarks/aggregation.py` `_failed_on_time`).
    A run holds one final result per Candidate."""

    def status(self) -> Literal["complete", "partial"]:
        """``complete`` only for a capture run whose copy opened and sealed and whose every call
        is stored. An empty run is complete: it has nothing a replay could miss."""
        complete = (
            self.mode == "capture"
            and not self.open_failed
            and self.sealed
            and not self.local
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
        counts = {reason: 0 for reason in _REASONS}
        for outcome in self._lost():
            counts[outcome.status] += 1
        counts["open"] += self.open_failed
        # A copy that opened and was never confirmed sealed — the seal failed, or never ran.
        counts["seal"] += self.frozen_copy_id is not None and not self.sealed
        counts["local"] += self.local
        for reason in _REASONS:
            if counts[reason]:
                attributes[f"{_PARTIAL_PREFIX}{reason}"] = counts[reason]
        return attributes

    def _lost(self) -> list[CaptureOutcome]:
        """The outcomes that are not stored and not forgiven.

        Q27 forgives no outcome: a call that left no entry at its key would be a replay miss, so a
        later call can never make up for it. R1 (OME-1775, spec §4)
        is the one exception. A call that gave the model no answer, in a Case that every final
        result failed, and that no later occurrence of the same request answered, is reproduced
        exactly by a replay: it misses, a miss is permanent, and the Case fails again.

        FEATURE: OME-1775 — spec §4 (R1 to R4).
        """
        answered_at: dict[tuple[str, Lane, str | None], int] = {}
        for outcome in self.outcomes:
            if outcome.answered and outcome.occurrence is not None:
                key = (outcome.case_key, outcome.lane, outcome.digest)
                answered_at[key] = max(answered_at.get(key, -1), outcome.occurrence)
        return [
            outcome
            for outcome in self.outcomes
            if outcome.status != "stored" and not self._forgiven(outcome, answered_at)
        ]

    def _forgiven(
        self,
        outcome: CaptureOutcome,
        answered_at: Mapping[tuple[str, Lane, str | None], int],
    ) -> bool:
        """True when a replay reproduces this outcome exactly, so the run is not partial (R1)."""
        # INVARIANT: a Case missing from ``case_results`` is never forgiven, and neither is a Case
        # that a replay may score (it scored for any Candidate, or it failed on time).
        # WHY: the retry guard exists because url4 ``retry=`` can retry a retryable no-answer
        # failure into an answer at the next occurrence in the capture (spec §4.1). A replay miss
        # is permanent and url4 never retries it, so the replay drops that member, and the Case
        # can score.
        return (
            outcome.status != "ambiguous"
            and not outcome.answered
            and outcome.case_id is not None
            and outcome.occurrence is not None
            and self.case_results.get(outcome.case_id) is False
            and answered_at.get((outcome.case_key, outcome.lane, outcome.digest), -1)
            <= outcome.occurrence
        )

    def next_occurrence(self, case_key: str, lane: Lane, digest: str) -> int:
        """Take the occurrence of one logical call, when it is first SENT (design §5.4).

        It counts the earlier logical calls of the same request in the same case key. A value is
        never given back, in capture or in replay: a call that failed keeps its place, so the next
        identical call in the case takes the next value in both runs.
        """
        key = (case_key, lane, digest)
        occurrence = self.occurrences.get(key, 0)
        self.occurrences[key] = occurrence + 1
        return occurrence


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


def record_case_results(results: Iterable[tuple[object, bool]]) -> None:
    """Note each final Case result (Case id, a replay may score it) in the bound tally. A no-op
    when none is bound. A Case that a replay may score in any result stays so. The caller
    (`finalize_candidate_result`) sets the flag for a Case that scored or that failed on time, so
    R1 never forgives the calls of such a Case."""

    tally = _tally.get()
    if tally is None:
        return
    for case_id, may_score in results:
        # WHY: str() — the activity side records `str()` of the Case id (`current_capture_case`).
        # The int 1 and the str "1" share a key, which only makes the rule stricter.
        key = str(case_id)
        tally.case_results[key] = tally.case_results.get(key, False) or may_score


__all__ = [
    "CALL_OCCURRENCE_HEADER",
    "CAPTURE_FIELD",
    "CASE_KEY_HEADER",
    "FROZEN_COPIES_PATH",
    "FROZEN_COPY_HEADER",
    "REPLAY_FIELD",
    "REPLAY_MISS",
    "REPLAY_UNAVAILABLE",
    "CaptureOutcome",
    "CaptureTally",
    "call_key_headers",
    "capture_outcomes",
    "case_key_for",
    "current_capture_tally",
    "record_capture_outcome",
    "record_case_results",
    "replay_chat_path",
    "replay_refusal_code",
    "request_digest",
    "seal_path",
    "tool_lookup_path",
    "tool_results_path",
]
