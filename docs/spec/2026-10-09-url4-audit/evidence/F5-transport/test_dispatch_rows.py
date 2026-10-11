"""Tie the boolean router encoding (_dispatch_spec.py) to the REAL routers, row by row.

For every ASSUME-reachable (has_q, endpoint, data, eval) row, build a real Url4Node,
dispatch the same target through the HTTP router (node.fetch -> _dispatch.dispatch)
and the direct router (dispatch_direct), and assert each outcome equals the
encoding. Also: status_for is total/deterministic over ErrorCode, and the codes
that fall through to the 500/502 fallback are listed.
"""

from __future__ import annotations

import itertools

import pytest

from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.peer._http import _STATUS_BY_CODE, status_for, status_for_code
from url4.peer.direct import _DIRECT_STATUS, dispatch_direct, http_status
from url4.peer.server import Url4Node

from _dispatch_spec import ASSUME, VARS, direct_outcome, http_outcome

ROWS = [
    dict(zip(VARS, bits, strict=True))
    for bits in itertools.product([False, True], repeat=4)
    if ASSUME(dict(zip(VARS, bits, strict=True)))
]


def _node_and_target(v):
    path = "/v1/x" if v["eval"] else "/x"
    node = Url4Node("t")
    if v["endpoint"]:
        node.endpoint(path)(lambda req: "ENDPOINT")
    if v["data"]:
        node.data(path, "DATA")

    async def fake_run_text(text, env=None, *, self_collection=None, processor=None):
        return "EVAL"

    node._run_text = fake_run_text  # dispatch only; evaluation is out of scope
    target = path + ("?q=(hello)!go" if v["has_q"] else "")
    return node, target


async def _classify(coro):
    try:
        body = await coro
    except Url4Error as exc:
        return f"{exc.code}"
    body = getattr(body, "body", body)
    return {"ENDPOINT": "endpoint", "DATA": "data", "EVAL": "eval"}[body]


def _strip(outcome):
    return outcome.split(":", 1)[1] if ":" in outcome else outcome


@pytest.mark.parametrize("v", ROWS, ids=lambda v: ",".join(f"{k}={int(b)}" for k, b in v.items()))
async def test_row_matches_encoding(v):
    node, target = _node_and_target(v)
    got_http = await _classify(node.fetch(target, relative=True))
    node, target = _node_and_target(v)
    got_direct = await _classify(dispatch_direct(node, target))
    assert (got_http, got_direct) == (_strip(http_outcome(v)), _strip(direct_outcome(v)))


def test_status_for_total_and_listed():
    rows = []
    for code in ErrorCode:
        for exc in (
            ResolutionError("x", code=code, permanent=True),
            ResolutionError("x", code=code, permanent=False),
            Url4Error("x", code=code, permanent=False),
            Url4Error("x", code=code, permanent=True),
        ):
            s = status_for(exc)
            assert isinstance(s, int) and 400 <= s <= 599
            assert s == status_for(exc)  # deterministic
            rows.append((code.value, type(exc).__name__, exc.permanent, s))
    fallback = sorted({c for c in ErrorCode if c not in _STATUS_BY_CODE})
    print("\nFALLBACK (500 permanent / 502 transient ResolutionError):", [c.value for c in fallback])
    # node vs direct tables never disagree on a code both list
    assert not (set(_STATUS_BY_CODE) & set(_DIRECT_STATUS))
    # MISSING_INTENT / DIRECT_EVAL_REFUSED through the NODE table -> server error
    for code in (ErrorCode.MISSING_INTENT, ErrorCode.DIRECT_EVAL_REFUSED, ErrorCode.UNKNOWN_PROCESSOR,
                 ErrorCode.TIMEOUT):
        print(code.value, "node:", status_for_code(code, permanent=True),
              "direct:", http_status(code, permanent=True))
    # a non-Resolution Url4Error flagged transient is still 500 (spec §4.1 row 'any other')
    assert status_for(ParseError("x", permanent=False)) == 400
    assert status_for(Url4Error("x", code="resolution_failed", permanent=False)) == 500
