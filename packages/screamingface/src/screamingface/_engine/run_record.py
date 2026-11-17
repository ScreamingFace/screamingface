"""A Candidate's outcome from the Engine's record (E5 P2 spec §4.3, D9).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who reattaches from another machine,
each Candidate's result reads exactly as it would have had I watched it run.

The runner folds each Candidate's frames into a record by the rules this Client used to apply
itself (`screamingface_engine/candidate_record.py`), and the Client reads that record instead of
folding: one fold, the same on every machine. Both are tested against the Engine's recorded runs.

INVARIANT: a Candidate that did not succeed raises what its terminal frame said, as the Client's
fold did: the error's message, code and permanence, with the frame's data as its details.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, NoReturn, cast

from screamingface._client_provenance import valid_client_version
from screamingface._core.ports import _RunOutcome, _RunResult
from screamingface._engine.contract import usage_value
from screamingface._engine.runs import CandidateRecord
from screamingface._report_primitives import capture_status_value
from screamingface.errors import ExecutionError
from screamingface.report import Usage

_ENDED = frozenset({"succeeded", "failed", "timed_out", "stopped", "lost"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def candidate_outcome(run_id: str, candidate: CandidateRecord) -> _RunOutcome:
    """The outcome of a Candidate that has ended, from its record; raises when it did not
    succeed. ``run_id`` is the Run's id, which names the Candidate's result route."""
    if candidate.state not in _ENDED:
        raise ValueError(f"Candidate {candidate.name!r} has not ended")
    record = candidate.record
    if candidate.state != "succeeded":
        raise _failure(candidate, record)
    if record is None:
        # §4.3: a succeeded Candidate whose record never reached the Engine (its child died
        # before reporting, or its outcome was rebuilt from the stream) has no result to read.
        raise ExecutionError(
            f"The SF Engine kept no record of Candidate {candidate.name!r}, so its result is lost",
            code="run_result_lost",
            permanent=True,
        )
    result = record.get("result")
    if result is None:
        raise ExecutionError("SF Engine succeeded without a root result")
    reference = _object(result)
    return _RunOutcome(
        run_id=_attempt(candidate),
        started_at=_time(record.get("started_at")),
        completed_at=_time(record.get("completed_at")),
        result_body=None,
        media_type=_optional(reference.get("media_type"), _text),
        root_usage=_optional(record.get("usage"), _usage),
        cache_saved_cost_usd=_optional(record.get("cache_saved_cost_usd"), _amount),
        cache_saved_cost_archive_usd=_optional(record.get("cache_saved_cost_archive_usd"), _amount),
        trace_id=_optional(record.get("trace_id"), _text),
        client_version=valid_client_version(record.get("client_version")),
        cache_hits=_count(record.get("cache_hits", 0)),
        cache_unpriced_hits=_optional(record.get("cache_unpriced_hits"), _count),
        frozen_copy_id=_optional(record.get("frozen_copy_id"), _text),
        capture_status=_capture_status(record.get("capture_status")),
        capture_replay=_optional(record.get("capture_replay"), _text),
        capture_partial_reasons=_reasons(record.get("capture_partial_reasons", [])),
        run_result=_RunResult(
            run_id=run_id,
            index=candidate.index,
            size_bytes=_count(reference.get("size_bytes")),
            sha256=_sha256(reference.get("sha256")),
        ),
    )


def _failure(candidate: CandidateRecord, record: Mapping[str, object] | None) -> ExecutionError:
    error = None if record is None else record.get("error")
    if error is None:
        # No runner reported (§4.3): stopped before it ran, refused at start, or lost.
        code = candidate.error_code or candidate.state
        return ExecutionError(f"SF Engine Run {candidate.state}", code=code)
    error = _object(error)
    permanent = error.get("permanent")
    if not (permanent is None or isinstance(permanent, bool)):
        _malformed()
    return ExecutionError(
        _text(error.get("message")),
        code=_text(error.get("code")),
        permanent=permanent,
        details=error.get("details"),
    )


def _attempt(candidate: CandidateRecord) -> str:
    # WHY the attempt: it is the topic the Candidate ran under, which is the run id its frames
    # carried and the id a saved result has always been keyed by.
    if candidate.attempt_id is None:
        _malformed()
    return candidate.attempt_id


def _usage(value: object) -> Usage:
    try:
        return usage_value(_object(value))
    except ExecutionError:
        _malformed()


def _capture_status(value: object) -> Literal["complete", "partial"] | None:
    try:
        return capture_status_value(value)
    except ValueError:
        _malformed()


def _reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _malformed()
    return tuple(cast(list[str], value))


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _malformed()
    return cast(Mapping[str, object], value)


def _optional[T](value: object, decode: Callable[[object], T]) -> T | None:
    return None if value is None else decode(value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        _malformed()
    return value


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _malformed()
    return value


def _sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _malformed()
    return value


def _amount(value: object) -> Decimal:
    # WHY a string only: the record writes money as a fixed-point string, never a float.
    if not isinstance(value, str):
        _malformed()
    try:
        amount = Decimal(value)
    except InvalidOperation:
        _malformed()
    if not amount.is_finite():
        _malformed()
    return amount


def _time(value: object) -> datetime:
    try:
        moment = datetime.fromisoformat(_text(value))
    except ValueError:
        _malformed()
    if moment.tzinfo is None:
        _malformed()
    return moment


def _malformed() -> NoReturn:
    raise ExecutionError(
        "The SF Engine sent a malformed Candidate record",
        code="engine_contract_error",
        permanent=True,
    )


__all__ = ["candidate_outcome"]
