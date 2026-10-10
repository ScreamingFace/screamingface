"""HTTP status mapping is total and listed (regression safety net, F5 audit).

Ported from ``evidence/F5-transport/test_dispatch_rows.py``: only the status-table
laws. The row-by-row router tie is not ported here.
"""

from __future__ import annotations

from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.peer._http import _STATUS_BY_CODE, status_for, status_for_code
from url4.peer.direct import _DIRECT_STATUS


def test_status_for_total_and_listed():
    for code in ErrorCode:
        for exc in (
            ResolutionError("x", code=code, permanent=True),
            ResolutionError("x", code=code, permanent=False),
            Url4Error("x", code=code, permanent=False),
            Url4Error("x", code=code, permanent=True),
        ):
            assert 400 <= status_for(exc) <= 599
    # node vs direct tables never disagree on a code both list
    assert not (set(_STATUS_BY_CODE) & set(_DIRECT_STATUS))
    # FLIPPED (url4 2.0, contracts C8): a non-Resolution Url4Error keeps its own class —
    # transient → 502 (was 500, which a Spec C §13.2.1 caller cannot tell apart).
    assert status_for(ParseError("x", permanent=False)) == 400
    assert status_for(Url4Error("x", code="resolution_failed", permanent=False)) == 502


def test_unlisted_resolution_error_is_502_whatever_its_class():
    # A source the node could not resolve is an upstream failure, even when it is permanent.
    assert status_for(ResolutionError("x", code="x.unlisted", permanent=True)) == 502
    assert status_for(ResolutionError("x", code="x.unlisted", permanent=False)) == 502
    # FLIPPED (url4 2.0, contracts C8): an unlisted permanent code → 422 (was 500).
    assert status_for(Url4Error("x", code="x.unlisted")) == 422


def test_admission_timeout_is_503():
    # No request was sent: this node's own concurrency cap is the cause.
    assert status_for(ResolutionError("x", code=ErrorCode.ADMISSION_TIMEOUT)) == 503


def test_unsupported_mode_is_501():
    # Spec C §13.2.1 has no row for it; 501 is the exact status for an unsupported mode.
    assert status_for_code("unsupported_mode", permanent=True) == 501


def test_intent_error_permanent_is_422():
    # No §13.2.1 status exists; 422 keeps the class (permanent) and the body carries the code.
    assert status_for_code("intent_error", permanent=True) == 422
    assert status_for(Url4Error("x", code=ErrorCode.INTENT_ERROR)) == 422


def test_unlisted_transient_code_is_502():
    assert status_for_code("x.unlisted", permanent=False) == 502


def test_internal_error_is_500():
    assert status_for_code(ErrorCode.INTERNAL_ERROR, permanent=True) == 500


def test_existing_rows_are_unchanged():
    assert status_for_code(ErrorCode.MALFORMED_SOURCE, permanent=True) == 400
    assert status_for_code(ErrorCode.ENDPOINT_NOT_FOUND, permanent=True) == 404


def test_unlisted_permanent_code_is_422():
    # C8 (row 30): a permanent code with no row must not read as transient (500).
    assert status_for_code(ErrorCode.QUORUM_NOT_MET, permanent=True) == 422
    assert status_for(Url4Error("x", code=ErrorCode.EXPANSION_NOT_ITERABLE)) == 422


def test_internal_and_codeless_failures_stay_500():
    assert status_for_code(ErrorCode.INTERNAL_ERROR, permanent=True) == 500
    assert status_for_code(None, permanent=True) == 500
