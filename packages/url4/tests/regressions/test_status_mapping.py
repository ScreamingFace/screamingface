"""HTTP status mapping is total and listed (regression safety net, F5 audit).

Ported from ``evidence/F5-transport/test_dispatch_rows.py``: only the status-table
laws. The row-by-row router tie is not ported here.
"""

from __future__ import annotations

from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.peer._http import _STATUS_BY_CODE, status_for
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
    # a non-Resolution Url4Error flagged transient is still 500 (spec §4.1 row 'any other')
    assert status_for(ParseError("x", permanent=False)) == 400
    assert status_for(Url4Error("x", code="resolution_failed", permanent=False)) == 500
