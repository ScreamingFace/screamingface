"""A Candidate's record, folded from the frames its run published (E5 P2 spec §4.3).

FEATURE: a detached Run (OME-1837). The Client used to fold each Candidate's frames itself, and a
Client that reattaches from another machine has none of them. So the runner folds them once, as
they are published, and reports the record with the Candidate's outcome.

INVARIANT: the Client's rules (`screamingface/_engine/contract.py`, `_RunState`): the same root,
the same cache evidence, the same provenance. Both folds are tested against the recorded runs in
`tests/fixtures/candidate_runs/`.

LAYERING: a shared leaf beside `run_evidence`, url4's protocol and the standard library only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from screamingface_engine.client_provenance import VERSION_ATTRIBUTE, valid_version
from url4.streaming.codec import encode
from url4.streaming.protocol import (
    CostUsageEvent,
    LogEvent,
    OutboundFrame,
    ResultEvent,
    SpanEvent,
    StartedEvent,
    TerminatedEvent,
)

MAX_RECORD_BYTES = 48 * 1024
"""The largest encoded record (§4.3). With the outcome's own fields it stays under the outcome's
64 KiB, and under the child's control-pipe line."""

# The run summary's attributes (`runner/cache_counters.py`, `capture_outcomes.py`), as the Client
# reads them. WHY named here: those modules are the run half's, which a shared leaf cannot import.
_CACHE_HITS = "cache.hits"
_REPORTED_HITS = "cache.saved_cost.reported_hits"
_ARCHIVE_HITS = "cache.saved_cost.archive_hits"
_UNPRICED_HITS = "cache.saved_cost.unpriced_hits"
_SAVED_COST_USD = "cache.saved_cost_usd"
_SAVED_COST_ARCHIVE_USD = "cache.saved_cost_archive_usd"
_FROZEN_COPY_ID = "capture.frozen_copy_id"
_CAPTURE_STATUS = "capture.status"
_CAPTURE_REPLAY = "capture.replay"
_PARTIAL_PREFIX = "capture.partial."

type _Attributes = Mapping[str, str | int | float | bool | None]


class CandidateRecordFold:
    """Folds one run's frames, in publish order, into its record."""

    def __init__(self, url4: str, *, trace_id: str | None) -> None:
        self._url4 = url4
        self._trace_id = trace_id
        self._root: str | None = None
        self._started_at: str | None = None
        self._version: str | None = None
        self._version_conflict = False
        self._summary: _Attributes | None = None
        self._summary_hits = 0
        self._hit_spans = 0
        self._saved: Decimal | None = None
        self._saved_archive: Decimal | None = None
        self._usage: dict[str, Any] | None = None
        self._result: dict[str, Any] | None = None
        self._terminated: TerminatedEvent | None = None

    def observe(self, frame: OutboundFrame) -> None:
        if isinstance(frame, StartedEvent):
            # The root is the first started frame naming the run's own url4, not the first one.
            if self._root is None and frame.data.url4 == self._url4:
                self._root = frame.source
                self._started_at = _time(frame)
        elif isinstance(frame, SpanEvent):
            self._span(frame)
        elif frame.source == self._root:
            # Provenance, usage, the result and the end are the root's alone.
            self._root_frame(frame)

    def _span(self, frame: SpanEvent) -> None:
        # Every span counts, the root's and its children's: each carries its own figures.
        if frame.data.cache_status == "hit":
            self._hit_spans += 1
        self._saved = _accumulated(self._saved, frame.data.cache_saved_cost_usd)
        self._saved_archive = _accumulated(
            self._saved_archive, frame.data.cache_saved_cost_archive_usd
        )

    def _root_frame(self, frame: OutboundFrame) -> None:
        if isinstance(frame, LogEvent):
            self._log(frame.data.attributes)
        elif isinstance(frame, CostUsageEvent) and frame.data.scope == "subtree":
            self._usage = _wire_data(frame)
        elif isinstance(frame, ResultEvent) and self._result is None:
            self._result = _result_ref(frame)
        elif isinstance(frame, TerminatedEvent) and self._terminated is None:
            self._terminated = frame

    def _log(self, attributes: _Attributes) -> None:
        raw = attributes.get(VERSION_ATTRIBUTE)
        version = valid_version(raw) if isinstance(raw, str) else None
        if version is not None:
            if self._version is not None and self._version != version:
                self._version_conflict = True
            self._version = version
        hits = _count(attributes.get(_CACHE_HITS))
        if hits is None:
            return
        self._summary_hits = max(self._summary_hits, hits)
        # The run's own tally only grows, so the largest summary is the latest complete one.
        current = None if self._summary is None else _count(self._summary.get(_CACHE_HITS))
        if current is None or hits >= current:
            self._summary = attributes

    def record(self) -> dict[str, Any] | None:
        """The record, cut to `MAX_RECORD_BYTES`; None until the root has ended, or when even
        the cut record is too large."""
        terminated = self._terminated
        if terminated is None:
            return None
        cache_hits = max(self._summary_hits, self._hit_spans)
        saved, saved_archive, unpriced = self._cache_evidence(cache_hits)
        summary = self._summary or {}
        record: dict[str, Any] = {
            "trace_id": self._trace_id,
            "started_at": self._started_at,
            "completed_at": _time(terminated),
            "usage": self._usage,
            "cache_hits": cache_hits,
            "cache_unpriced_hits": unpriced,
            "cache_saved_cost_usd": _amount(saved),
            "cache_saved_cost_archive_usd": _amount(saved_archive),
            "frozen_copy_id": _text(summary.get(_FROZEN_COPY_ID)),
            "capture_status": _capture_status(summary.get(_CAPTURE_STATUS)),
            "capture_replay": _text(summary.get(_CAPTURE_REPLAY)),
            "capture_partial_reasons": _partial_reasons(summary),
            "client_version": None if self._version_conflict else self._version,
        }
        status = terminated.data.status
        if status != "succeeded":
            # What the Client raises with, from the same terminal frame.
            error = terminated.data.error
            record["error"] = {
                "code": status if error is None else error.code,
                "message": f"SF Engine Run {status}" if error is None else error.message,
                "permanent": None if error is None else error.permanent,
                "details": _wire_data(terminated),
            }
        elif self._result is not None:
            record["result"] = self._result
        return fit_record(record)

    def _cache_evidence(self, cache_hits: int) -> tuple[Decimal | None, Decimal | None, int | None]:
        """The two saving totals and the unpriced-hit count, from one body of evidence: the
        summary's when it carries its coverage counts, else the spans'. The count is published
        only when the summary agrees with itself and with the run's hits (the Client's rule)."""
        summary = self._summary
        unpriced = None if summary is None else _count(summary.get(_UNPRICED_HITS))
        if summary is None or unpriced is None:
            return self._saved, self._saved_archive, None
        hits = _count(summary.get(_CACHE_HITS))
        reported = _count(summary.get(_REPORTED_HITS))
        archive = _count(summary.get(_ARCHIVE_HITS))
        saved = _decimal(summary.get(_SAVED_COST_USD))
        saved_archive = _decimal(summary.get(_SAVED_COST_ARCHIVE_USD))
        consistent = (
            hits == cache_hits
            and reported is not None
            and archive is not None
            and reported + archive + unpriced == hits
            and (reported > 0) == (saved is not None)
            and (archive > 0) == (saved_archive is not None)
        )
        return saved, saved_archive, unpriced if consistent else None


def fit_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """``record`` under `MAX_RECORD_BYTES`: the error's details, then its message, then the
    capture reasons are cut, each named under `cut`. None when it is still larger (§4.3)."""
    if _size(record) <= MAX_RECORD_BYTES:
        return record
    cut: list[str] = []
    record = {**record, "cut": cut}
    error = record.get("error")
    if isinstance(error, dict):
        error = record["error"] = dict(error)
        if error.get("details") is not None:
            error["details"] = None
            cut.append("error.details")
        message = error.get("message")
        if _size(record) > MAX_RECORD_BYTES and isinstance(message, str) and message:
            cut.append("error.message")
            error["message"] = _cut_text(message, _size(record) - MAX_RECORD_BYTES)
            excess = _size(record) - MAX_RECORD_BYTES
            if excess > 0:
                # Each character removed is at least one encoded byte, so this always fits.
                error["message"] = error["message"][: max(0, len(error["message"]) - excess)]
    reasons = record.get("capture_partial_reasons")
    if _size(record) > MAX_RECORD_BYTES and isinstance(reasons, list) and reasons:
        cut.append("capture_partial_reasons")
        excess = _size(record) - MAX_RECORD_BYTES
        kept = list(reasons)
        while kept and excess > 0:
            # An entry and its separating comma.
            excess -= len(json.dumps(kept.pop())) + 1
        record["capture_partial_reasons"] = kept
    return record if _size(record) <= MAX_RECORD_BYTES else None


def _cut_text(text: str, excess: int) -> str:
    """``text`` shortened by about ``excess`` encoded bytes, in proportion to its encoded size,
    so text whose characters encode to several bytes keeps as much as fits."""
    encoded = len(json.dumps(text)) - 2
    return text[: max(0, (encoded - excess) * len(text) // encoded)]


def _size(record: Mapping[str, Any]) -> int:
    # WHY ASCII-escaped: the outcome codec writes it so, and an escape is never shorter than the
    # character's UTF-8 bytes, so this bounds every carrier.
    return len(json.dumps(record, separators=(",", ":")).encode())


def _wire_data(frame: OutboundFrame) -> dict[str, Any]:
    """The frame's `data` exactly as the Client receives it."""
    return json.loads(encode(frame))["data"]


def _result_ref(frame: ResultEvent) -> dict[str, Any]:
    """The result's media type, size and checksum: the run-results store keys it by the checksum
    (spec D9a)."""
    data = frame.data
    if data.artifact is not None:
        size, digest = data.artifact.size_bytes, data.artifact.sha256
    else:
        body = (data.body or "").encode()
        size, digest = len(body), hashlib.sha256(body).hexdigest()
    return {"media_type": data.media_type, "size_bytes": size, "sha256": digest}


def _time(frame: OutboundFrame) -> str | None:
    return None if frame.time is None else frame.time.isoformat()


def _accumulated(total: Decimal | None, amount: Decimal | None) -> Decimal | None:
    """Absent stays distinct from zero: a run that observed nothing priceable stays None."""
    if amount is None:
        return total
    return amount if total is None else total + amount


def _amount(value: Decimal | None) -> str | None:
    # WHY a fixed-point string: a float would round the money, and `str` may use an exponent.
    return None if value is None else format(value, "f")


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _capture_status(value: object) -> str | None:
    return value if value in ("complete", "partial") else None


def _partial_reasons(summary: _Attributes) -> list[str]:
    return sorted(
        key.removeprefix(_PARTIAL_PREFIX)
        for key, value in summary.items()
        if key.startswith(_PARTIAL_PREFIX) and (_count(value) or 0) > 0
    )


__all__ = ["MAX_RECORD_BYTES", "CandidateRecordFold", "fit_record"]
