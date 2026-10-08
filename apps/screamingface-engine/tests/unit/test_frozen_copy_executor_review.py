"""E14 F-B3 review — a failed capture run still states its copy; the copy helpers never raise.

FEATURE: OME-1307 (design §5.2 items 4, 6). A capture run seals its copy and writes
`capture.frozen_copy_id`, `capture.status` and `capture.partial.*` ALSO when the run fails, and a
replay run writes `capture.replay` also when it fails. A failed run states no cost and no cache
counts, so only the `capture.*` attributes are written. A normal failed run writes nothing new.
A copy that cannot open or seal because of an UNEXPECTED error is still a partial run, not a crash.

A separate module (append-only gate).
"""

from __future__ import annotations

import httpx
import pytest
from frozen_copy_support import (
    COPY,
    Gateway,
    capture_scope,
    chat,
    replay_scope,
    stored,
)
from test_frozen_copy_executor import _attributes, _capture_attributes, _run

from screamingface_engine.request_scope import RequestScope
from url4.core.errors import ResolutionError
from url4.streaming.protocol import LogData


def _lines(logs: list[LogData]) -> list[LogData]:
    """The log frames that state the run's frozen-copy state (a failed run's line has no cache
    counters, so it is told apart by its `capture.*` attributes)."""
    return [log for log in logs if any(key.startswith("capture.") for key in log.attributes)]


def _stored_400() -> httpx.Response:
    return httpx.Response(400, headers=stored(), json={"detail": {"code": "bad_request"}})


@pytest.mark.asyncio
async def test_a_failed_capture_run_still_writes_its_capture_summary() -> None:
    summary, logs, failure = await _run(Gateway([_stored_400()]), capture_scope())

    assert isinstance(failure, ResolutionError)
    assert summary is not None and summary.outcome == "failed"
    # Only the capture attributes: a failed run's cache counters are not exact.
    assert summary.cache_attributes == {
        "capture.frozen_copy_id": COPY,
        "capture.status": "complete",
    }
    (line,) = _lines(logs)
    assert dict(line.attributes) == summary.cache_attributes


@pytest.mark.asyncio
async def test_a_failed_capture_run_that_was_not_confirmed_is_partial() -> None:
    summary, logs, _failure = await _run(
        Gateway([httpx.Response(400, json={"detail": {"code": "bad_request"}})]), capture_scope()
    )

    assert _capture_attributes(summary) == {
        "capture.frozen_copy_id": COPY,
        "capture.status": "partial",
        "capture.partial.missing": 1,
    }
    assert dict(_lines(logs)[0].attributes) == _attributes(summary)


@pytest.mark.asyncio
async def test_a_failed_replay_run_still_writes_capture_replay() -> None:
    gateway = Gateway(
        replay_steps=[httpx.Response(404, json={"detail": {"code": "frozen_copy_miss"}})]
    )

    summary, logs, failure = await _run(gateway, replay_scope())

    assert isinstance(failure, ResolutionError)
    assert summary is not None and summary.cache_attributes == {"capture.replay": COPY}
    (line,) = _lines(logs)
    assert dict(line.attributes) == {"capture.replay": COPY}


@pytest.mark.asyncio
async def test_a_failed_normal_run_writes_nothing_new() -> None:
    summary, logs, failure = await _run(Gateway([_stored_400()]), RequestScope(origin="run"))

    assert isinstance(failure, ResolutionError)
    assert summary is not None and summary.outcome == "failed"
    assert summary.cache_attributes is None
    assert _lines(logs) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("open_response", "seal_response", "expected"),
    [
        (
            RuntimeError("boom"),
            None,
            {"capture.status": "partial", "capture.partial.open": 1},
        ),
        (
            None,
            RuntimeError("boom"),
            {
                "capture.frozen_copy_id": COPY,
                "capture.status": "partial",
                "capture.partial.seal": 1,
            },
        ),
    ],
    ids=["open", "seal"],
)
async def test_an_unexpected_error_opening_or_sealing_makes_the_run_partial_not_a_crash(
    open_response: BaseException | None,
    seal_response: BaseException | None,
    expected: dict[str, object],
) -> None:
    gateway = Gateway(
        [chat("done", stored())], open_response=open_response, seal_response=seal_response
    )

    summary, _logs, failure = await _run(gateway, capture_scope())

    assert failure is None
    assert summary is not None and summary.outcome == "succeeded"
    assert _capture_attributes(summary) == expected
