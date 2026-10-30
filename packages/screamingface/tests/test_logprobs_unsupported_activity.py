"""The SDK activity view carries the `logprobs_unsupported` failure code (E4b part 3, P6).

Pins LC#11 (c): the SDK decodes an activity record whose `failure_code` is `logprobs_unsupported`
and the activity log counts it as valid. A separate module (append-only gate).
"""

from __future__ import annotations

from datetime import UTC, datetime

from screamingface._ui.activity_record import decode
from screamingface._ui.activity_state import ActivityLog
from screamingface.events import Log


def _failed(code: str) -> Log:
    attributes = {
        "schema": "screamingface.activity.v1",
        "id": "op",
        "revision": 2,
        "kind": "model_call",
        "state": "failed",
        "elapsed_ms": 1200,
        "observed_at_ms": 100000,
        "failure_code": code,
    }
    return Log(
        id="op-2",
        run_id="run",
        sequence=1,
        timestamp=datetime.now(UTC),
        source="/node",
        severity_number=9,
        severity_text="INFO",
        body="Activity",
        attributes={"sf.activity." + key: value for key, value in attributes.items()},
    )


def test_the_activity_view_carries_logprobs_unsupported() -> None:
    record = decode(_failed("logprobs_unsupported"))
    assert dict(record.facts)["failure_code"] == "logprobs_unsupported"
    view = ActivityLog()
    view.observe(0, _failed("logprobs_unsupported"))
    assert view.invalid == 0
