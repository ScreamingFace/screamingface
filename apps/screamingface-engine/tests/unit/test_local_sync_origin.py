"""C1 (batch C review, FX-6) — local mode's mount now binds the run-context log identity too.

# WHY this file exists. Before C1, `local._LocalNodeMount` bound the request scope and the trace
# (`trace_scope`) but not `logs.run_scope` — the ONE thing that renders `origin=`/`trace_id=` onto
# a log line (see `logs.RunContextFilter`). The node tier's own `_dispatch` bound all three, so a
# sync request answered by the deployed tier logged its identity and a request answered by
# `serve --local` did not. C1 extracts ONE shared binding, `request_scope.bind_sync_request`, and
# uses it in both places — this test pins the local mount's half of that: a log line emitted
# while a direct-mount request is in flight now carries `origin=sync` and the caller's trace id,
# exactly as the tier's own origin test already pins — see the FX-6 test in
# test_node_tier_dispatch_fixes.py.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import httpx
import pytest

from screamingface_engine.local import _LocalNodeMount
from screamingface_engine.logs import APP_LOGGER, configure

_TRACE = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
_TRACE_ID = "a" * 32

_PROBE_LOGGER = "screamingface_engine.local_sync_origin_probe"


@pytest.fixture
def _restore_app_logger() -> Any:
    """Isolate the `screamingface_engine` logger's handlers/level, like the tier's own fixture."""
    logger = logging.getLogger(APP_LOGGER)
    handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    logger.handlers.clear()
    try:
        yield
    finally:
        logger.handlers.clear()
        logger.handlers.extend(handlers)
        logger.setLevel(level)
        logger.propagate = propagate


def _logging_inner() -> Any:
    """An inner ASGI app that logs one line while handling the request, then answers 200."""

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        logging.getLogger(_PROBE_LOGGER).info("handling mount")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return inner


def _local_client(inner: Any) -> httpx.AsyncClient:
    mount = _LocalNodeMount({"asgi": inner})
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=mount), base_url="http://app.test")


@pytest.mark.asyncio
async def test_a_local_direct_mount_request_logs_with_origin_sync_and_the_trace_id(
    _restore_app_logger: None,
) -> None:
    """FX-6: the local mount's `bind_sync_request` call now binds `logs.run_scope(origin="sync")`
    too, so a log line emitted while it handles a request carries that identity — before C1 this
    line carried neither `origin=` nor `trace_id=`."""
    stream = io.StringIO()
    configure(stream)

    async with _local_client(_logging_inner()) as client:
        response = await client.get("/m", headers={"traceparent": _TRACE})

    assert response.status_code == 200, response.text
    lines = [line for line in stream.getvalue().splitlines() if "handling mount" in line]
    assert len(lines) == 1, stream.getvalue()
    assert "origin=sync" in lines[0]
    assert f"trace_id={_TRACE_ID}" in lines[0]


@pytest.mark.asyncio
async def test_a_local_direct_mount_request_with_no_trace_still_logs_origin_sync(
    _restore_app_logger: None,
) -> None:
    """`origin=sync` does not depend on a caller sending a `traceparent` (matching the tier)."""
    stream = io.StringIO()
    configure(stream)

    async with _local_client(_logging_inner()) as client:
        response = await client.get("/m")

    assert response.status_code == 200, response.text
    lines = [line for line in stream.getvalue().splitlines() if "handling mount" in line]
    assert len(lines) == 1, stream.getvalue()
    assert "origin=sync" in lines[0]
    assert "trace_id=" not in lines[0]
