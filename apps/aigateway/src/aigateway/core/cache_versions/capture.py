"""The pure mapper from one call to one capture record (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - the index row of a traced call is thin: the prompt lives once per key in
``request_cache_prompt``, and a response body is inline only when no cache row holds it (CV-D8).

INVARIANT: PURE. No I/O, no clock, no logging. A serialisation error propagates: the route helper
counts it as a capture failure and the chat response is unchanged.
"""

from __future__ import annotations

import json

from .ports import CAPTURE_OUTCOMES, INLINE_OUTCOMES, CaptureKey, CaptureOutcome, CaptureRecord


def capture_record(
    *,
    account_id: str,
    trace_id: str,
    outcome: CaptureOutcome,
    key: CaptureKey | None,
    response: object | None,
) -> CaptureRecord:
    if outcome not in CAPTURE_OUTCOMES:
        # A programming error, not a runtime condition: the route passes literals only.
        raise ValueError(f"unknown capture outcome: {outcome!r}")
    response_json: str | None = None
    if outcome in INLINE_OUTCOMES and key is not None and isinstance(response, dict):
        response_json = json.dumps(
            response, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    return CaptureRecord(
        account_id=account_id,
        trace_id=trace_id,
        outcome=outcome,
        key_hash=key.key_hash if key is not None else None,
        request_material=key.material if key is not None else None,
        response_json=response_json,
    )
