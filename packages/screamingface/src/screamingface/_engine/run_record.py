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

from collections.abc import Mapping
from typing import Literal, cast

from screamingface._client_provenance import valid_client_version
from screamingface._core.ports import CANDIDATE_ENDED, _RunOutcome, _RunResult
from screamingface._engine.contract import usage_value
from screamingface._engine.runs import _SHA256, CandidateRecord
from screamingface._engine.wire_checks import WireChecks
from screamingface._report_primitives import capture_status_value
from screamingface.errors import ExecutionError
from screamingface.report import Usage


def candidate_outcome(run_id: str, candidate: CandidateRecord) -> _RunOutcome:
    """The outcome of a Candidate that has ended, from its record; raises when it did not
    succeed. ``run_id`` is the Run's id, which names the Candidate's result route."""
    if candidate.state not in CANDIDATE_ENDED:
        # WHY a contract error (#1878 review): a state this Client does not know as an end (a
        # newer Engine's, say) failed the Candidate with a bare ValueError, with no code and no
        # hint, even when it succeeded on the Engine.
        raise ExecutionError(
            f"The SF Engine reports Candidate {candidate.name!r} as {candidate.state!r}, which "
            "this Client does not know as an end",
            code="engine_contract_error",
            permanent=True,
            hint="Upgrade the screamingface Client.",
        )
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
    message = error.get("message")
    # WHY any string: the Engine trims an oversized record's message, possibly to nothing,
    # and the Client's fold read it as any string; the Candidate still fails with its code.
    if not isinstance(message, str):
        _malformed()
    code = _text(error.get("code"))
    return ExecutionError(
        message,
        # WHY the row's first (#1878 review): the Candidate's error code is first-wins on the
        # Engine; the record gives the message and details.
        code=candidate.error_code or code,
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


_CHECK = WireChecks("The SF Engine sent a malformed Candidate record")
_object = _CHECK.object
_optional = WireChecks.optional
_text = _CHECK.text
_count = _CHECK.count
_time = _CHECK.time
_amount = _CHECK.decimal
_malformed = _CHECK.malformed


def _sha256(value: object) -> str:
    return _CHECK.matching(value, _SHA256)


__all__ = ["candidate_outcome"]
