"""The caller's run limits, read from the SF Engine (OME-1314).

FEATURE: the Client sizes its Candidate fan-out from ``GET /v1/limits`` — the per-caller in-flight
cap the Engine's admission enforces — so it never sends more runs at once than the Engine admits
(spec 2026-11-10-per-user-parallel-runs D3).

INVARIANT: this read never fails an Evaluation. Any failure — a non-200 answer (an Engine older
than OME-1314 answers 404), a transport error, a body that is not JSON, or a value that is not a
positive integer — returns ``DEFAULT_CALLER_INFLIGHT_CAP``.

Each fallback logs one DEBUG line with the status code or the exception type, never the body, so
"only 8 run at once" can be traced to its cause (#1745 review).
"""

from __future__ import annotations

import logging

import httpx

from screamingface._core.wire import _REPLAY_SAFE
from screamingface._evaluation.runner import _MAX_CANDIDATES_IN_FLIGHT

_logger = logging.getLogger(__name__)

_LIMITS_PATH = "/v1/limits"
# WHY the runner's fallback: it is the fan-out before OME-1314 and the per-caller cap an older
# Engine admits, so a new Client never overruns an old Engine. One definition, in the runner.
DEFAULT_CALLER_INFLIGHT_CAP = _MAX_CANDIDATES_IN_FLIGHT


def caller_inflight_cap_sync(http: httpx.Client) -> int:
    """The Engine's per-caller in-flight cap, or ``DEFAULT_CALLER_INFLIGHT_CAP``. Never raises."""
    try:
        response = http.get(_LIMITS_PATH, extensions={_REPLAY_SAFE: True})
    except Exception as error:  # noqa: BLE001 - spec D3: this read never fails an Evaluation
        return _fallback("the request failed:", type(error).__name__)
    return _cap_from(response)


async def caller_inflight_cap_async(http: httpx.AsyncClient) -> int:
    """The async twin of ``caller_inflight_cap_sync``."""
    try:
        response = await http.get(_LIMITS_PATH, extensions={_REPLAY_SAFE: True})
    except Exception as error:  # noqa: BLE001 - spec D3: this read never fails an Evaluation
        return _fallback("the request failed:", type(error).__name__)
    return _cap_from(response)


def _cap_from(response: httpx.Response) -> int:
    if response.status_code != 200:
        return _fallback("it answered HTTP", response.status_code)
    try:
        body: object = response.json()
    except ValueError:
        body = None
    cap = body.get("caller_inflight_cap") if isinstance(body, dict) else None
    # WHY the bool check: `True` is an `int` in Python and must not read as a cap of 1.
    if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 1:
        return cap
    return _fallback("its body is not JSON with a positive integer caller_inflight_cap, HTTP", 200)


def _fallback(reason: str, detail: object) -> int:
    """Log why the Engine's cap was not read, then give the fallback. ``detail`` is a status
    code or an exception type name: never a response body, which may carry the caller's data."""
    _logger.debug(
        "SF Engine %s not used, %s %s; running at most %d Candidates at once",
        _LIMITS_PATH,
        reason,
        detail,
        DEFAULT_CALLER_INFLIGHT_CAP,
    )
    return DEFAULT_CALLER_INFLIGHT_CAP


__all__ = ["DEFAULT_CALLER_INFLIGHT_CAP", "caller_inflight_cap_async", "caller_inflight_cap_sync"]
