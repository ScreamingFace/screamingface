"""E14 F-B3 review — only the run route honours `X-Capture` and `X-Replay-Frozen-Copy`.

FEATURE: OME-1307 (design §5.1, pinned 2026-10-08). The mount routes and the local eval path answer
400 `capture_unsupported` when either header is PRESENT, before anything is scheduled or run. A
silent ignore would run a paid, uncaptured call for a caller who asked for a capture or a replay.

A separate module (append-only gate).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from frozen_copy_support import COPY
from test_mount_routes import _app, _client, _error, _ok

from screamingface_engine.local import _LocalNodeMount
from screamingface_engine.request_scope import (
    CAPTURE_HEADER,
    REPLAY_FROZEN_COPY_HEADER,
    current_scope,
    forwarded_headers,
    request_scope_from_headers,
)

_EMAIL = {"X-User-Email": "caller@example.com"}
_PRESENT = [
    {CAPTURE_HEADER: "true"},
    {REPLAY_FROZEN_COPY_HEADER: COPY},
    {CAPTURE_HEADER: "whatever"},
    {REPLAY_FROZEN_COPY_HEADER: "garbage"},
    {CAPTURE_HEADER: "true", REPLAY_FROZEN_COPY_HEADER: COPY},
    {CAPTURE_HEADER: ""},
]
_IDS = ["capture", "replay", "capture-junk", "replay-junk", "both", "blank"]


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", _PRESENT, ids=_IDS)
async def test_a_mount_route_refuses_the_header_and_schedules_nothing(
    headers: Mapping[str, str],
) -> None:
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers={**_EMAIL, **headers})

    assert resp.status_code == 400
    assert _error(resp)["code"] == "capture_unsupported"
    assert runner.scheduled == []


@pytest.mark.asyncio
async def test_a_mount_route_without_the_headers_still_runs() -> None:
    app, runner = _app(_ok("x"))
    async with _client(app) as client:
        resp = await client.get("/v1/chat/completions?q=(a)!b", headers=_EMAIL)

    assert resp.status_code == 200
    assert len(runner.scheduled) == 1


class _Recorder:
    def __init__(self) -> None:
        self.reached = False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.reached = True
        current_scope()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", _PRESENT, ids=_IDS)
async def test_the_local_eval_path_refuses_the_header_before_the_handler_runs(
    headers: Mapping[str, str],
) -> None:
    recorder = _Recorder()
    mount = _LocalNodeMount({"asgi": recorder})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mount), base_url="http://app.test"
    ) as client:
        response = await client.get("/m", headers=dict(headers))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "capture_unsupported"
    assert recorder.reached is False


def test_the_sync_producer_and_the_forwarder_never_carry_the_mode() -> None:
    scope = request_scope_from_headers({CAPTURE_HEADER: "true"})
    replay = request_scope_from_headers({REPLAY_FROZEN_COPY_HEADER: COPY})
    forwarded = forwarded_headers(
        [(CAPTURE_HEADER, "true"), (REPLAY_FROZEN_COPY_HEADER, COPY)], verified_identity={}
    )

    assert (scope.capture, scope.replay_frozen_copy) == (False, None)
    assert (replay.capture, replay.replay_frozen_copy) == (False, None)
    assert forwarded == []
