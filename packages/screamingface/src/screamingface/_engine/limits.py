"""The caller's run limits, read from the SF Engine (OME-1314).

FEATURE: the Client sizes its Candidate fan-out from ``GET /v1/limits`` — the per-caller in-flight
cap the Engine's admission enforces — so it never sends more runs at once than the Engine admits
(spec 2026-11-10-per-user-parallel-runs D3).

INVARIANT: this read never fails an Evaluation. Any failure — a non-200 answer (an Engine older
than OME-1314 answers 404), a transport error, a body that is not JSON, or a value that is not a
positive integer — returns ``DEFAULT_CALLER_INFLIGHT_CAP``.
"""

from __future__ import annotations

import httpx

from screamingface._core.wire import _REPLAY_SAFE
from screamingface._evaluation.runner import _MAX_CANDIDATES_IN_FLIGHT

_LIMITS_PATH = "/v1/limits"
# WHY the runner's fallback: it is the fan-out before OME-1314 and the per-caller cap an older
# Engine admits, so a new Client never overruns an old Engine. One definition, in the runner.
DEFAULT_CALLER_INFLIGHT_CAP = _MAX_CANDIDATES_IN_FLIGHT


def caller_inflight_cap_sync(http: httpx.Client) -> int:
    """The Engine's per-caller in-flight cap, or ``DEFAULT_CALLER_INFLIGHT_CAP``. Never raises."""
    try:
        response = http.get(_LIMITS_PATH, extensions={_REPLAY_SAFE: True})
    except Exception:  # noqa: BLE001 - spec D3: this read never fails an Evaluation
        return DEFAULT_CALLER_INFLIGHT_CAP
    return _cap_from(response)


async def caller_inflight_cap_async(http: httpx.AsyncClient) -> int:
    """The async twin of ``caller_inflight_cap_sync``."""
    try:
        response = await http.get(_LIMITS_PATH, extensions={_REPLAY_SAFE: True})
    except Exception:  # noqa: BLE001 - spec D3: this read never fails an Evaluation
        return DEFAULT_CALLER_INFLIGHT_CAP
    return _cap_from(response)


def _cap_from(response: httpx.Response) -> int:
    body: object = None
    if response.status_code == 200:
        try:
            body = response.json()
        except ValueError:
            body = None
    cap = body.get("caller_inflight_cap") if isinstance(body, dict) else None
    # WHY the bool check: `True` is an `int` in Python and must not read as a cap of 1.
    if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 1:
        return cap
    return DEFAULT_CALLER_INFLIGHT_CAP


__all__ = ["DEFAULT_CALLER_INFLIGHT_CAP", "caller_inflight_cap_async", "caller_inflight_cap_sync"]
