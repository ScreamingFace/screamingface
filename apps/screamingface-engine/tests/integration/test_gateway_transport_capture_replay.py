"""Characterization test for the capture and replay legs of the gateway round trip, written
before the move.

FEATURE: shared gateway round trip (PRD `gateway-transport.md`, GT-S6). The capture and replay
branch (`_recorded_completion`, `_fetch_replay`, `_CaptureProbe`) moves from `world/connector.py`
to `world/gateway_transport.py` with no body change. This test drives one capture call and one
replay call of the same logical call through the production endpoint (`build_aigateway_world` and
url4 `run`) and pins the request each one sends and what each one records.

INVARIANT: each golden is a literal recorded from the code of today. Do not regenerate a golden
to make the move pass.

AIDEV-NOTE: a small fake gateway of its own, because the shared `frozen_copy_support` lives in
`tests/unit`, which is not on the import path of an integration test. The only private
`connector` name is in `_no_waits`: after the move, retarget that one line.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.capture_outcomes import CaptureTally, capture_outcomes, request_digest
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import connector
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import ModelResponse, ObservationEvent, Usage

_MODEL = "anthropic/claude-haiku-4-5"
_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"
_EXPRESSION = f"/{_MODEL}?temperature=0.25&q=('the context')!'the intent'"
_CONFIG = AigatewayConfig(
    models=(ModelSpec(id=_MODEL, web_search=False),),
    default_model=_MODEL,
    timeout_s=45.0,
    queue_timeout_s=15.0,
)
_HTTPX_OWN_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "connection",
        "content-length",
        "content-type",
        "host",
        "user-agent",
    }
)
_ANSWER_BODY: dict[str, Any] = {
    "choices": [
        {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 651, "completion_tokens": 25},
}


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero every retry wait.

    AIDEV-NOTE: the ONE private `connector` name in this file. After the move, patch it on
    `gateway_transport` instead.
    """

    async def no_wait(_attempt: int, _delay: float) -> None:
        return None

    monkeypatch.setattr(connector, "_wait_to_retry", no_wait)


class _FakeGateway:
    """Answers every request with `reply`, and keeps each request's path, headers and body."""

    def __init__(self, reply: httpx.Response) -> None:
        self._reply = reply
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        headers = {
            name.lower(): value
            for name, value in request.headers.items()
            if name.lower() not in _HTTPX_OWN_HEADERS
        }
        self.requests.append((request.url.path, headers, json.loads(request.content)))
        return self._reply

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    def reports(self) -> list[Usage | ModelResponse]:
        """The usage and response records, with the span id cleared.

        WHY cleared: url4 mints a random span id per run; it is not part of the round trip.
        """
        return [
            dataclasses.replace(event, span_id=None)
            for event in self.events
            if isinstance(event, Usage | ModelResponse)
        ]


async def _call(
    gateway: _FakeGateway, scope: RequestScope, recorder: _Recorder
) -> tuple[CaptureTally, str]:
    """One model call of Case 1 under `scope`, with the run's tally bound as the executor binds
    it: capture mode with the opened copy, or replay mode with the replayed copy."""
    async with gateway.client() as client:
        world = await build_aigateway_world(_CONFIG, client=client)
        with case_scope(1), request_scope(scope), capture_outcomes() as tally:
            if scope.replay_frozen_copy is not None:
                tally.mode, tally.frozen_copy_id = "replay", scope.replay_frozen_copy
            else:
                tally.mode, tally.frozen_copy_id = "capture", _COPY
            answer = await url4_run(_EXPRESSION, io=world.node, observer=recorder)
    return tally, answer


# ── the goldens ────────────────────────────────────────────────────────────────────────────

_GOLDEN_BODY = {
    "model": "anthropic/claude-haiku-4-5",
    "messages": [
        {"role": "system", "content": "the intent"},
        {"role": "user", "content": "the context"},
    ],
    "temperature": 0.25,
}
"""INVARIANT: capture adds headers only. The capture body and the replay body are both this plain
body, with no cache field and no frozen-copy field."""
_GOLDEN_CASE_KEY = "d193ed289ab3b781af1f6b934e2d0c63"
_GOLDEN_DIGEST = "59c1e9dbdf7c1d559e3cb1a0d0487ef616454fd4135edcde84de81c395799ddd"
_GOLDEN_CAPTURE_REQUEST = (
    "/v1/chat/completions",
    {
        "x-aigw-execution-timeout-s": "45.0",
        "x-aigw-queue-timeout-s": "15.0",
        "x-aigw-frozen-copy": "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11",
        "x-aigw-case-key": _GOLDEN_CASE_KEY,
        "x-aigw-call-occurrence": "0",
    },
    _GOLDEN_BODY,
)
_GOLDEN_CAPTURE_OUTCOMES = [
    {
        "lane": "chat",
        "status": "stored",
        "digest": _GOLDEN_DIGEST,
        "case_id": "1",
        "case_key": _GOLDEN_CASE_KEY,
        "occurrence": 0,
        "replay_failure": None,
        "answered": True,
    }
]
_GOLDEN_REPLAY_REQUEST = (
    "/v1/frozen-copies/6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11/chat/completions",
    {
        "x-aigw-execution-timeout-s": "45.0",
        "x-aigw-queue-timeout-s": "15.0",
        "x-aigw-case-key": _GOLDEN_CASE_KEY,
        "x-aigw-call-occurrence": "0",
    },
    _GOLDEN_BODY,
)
# WHY these records: a replayed answer is accounted like a cache hit that spent nothing.
_GOLDEN_REPLAY_REPORTS: list[Usage | ModelResponse] = [
    Usage(
        span_id=None,
        provider="anthropic",
        model=_MODEL,
        input_tokens=0,
        output_tokens=0,
        response_model=None,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        cost_usd=Decimal("0"),
        image_and_file_tokens=None,
    ),
    ModelResponse(span_id=None, finish_reason="stop", refusal=None, cache_status="hit"),
]


@pytest.mark.asyncio
async def test_capture_and_replay_digests_match_golden() -> None:
    """GT-7: one capture call and one replay call send and record the golden values."""
    capture = _FakeGateway(
        httpx.Response(200, headers={"X-AIGW-Capture": "stored"}, json=_ANSWER_BODY)
    )
    capture_tally, capture_answer = await _call(
        capture, RequestScope(origin="run", capture=True), _Recorder()
    )
    replay = _FakeGateway(
        httpx.Response(
            200, headers={"X-AIGW-Replay": "hit"}, json={**_ANSWER_BODY, "frozen_copy_replay": True}
        )
    )
    recorder = _Recorder()
    replay_tally, replay_answer = await _call(
        replay, RequestScope(origin="run", replay_frozen_copy=_COPY), recorder
    )

    assert (capture_answer, replay_answer) == ("an answer", "an answer")
    assert capture.requests == [_GOLDEN_CAPTURE_REQUEST]
    assert [dataclasses.asdict(o) for o in capture_tally.outcomes] == _GOLDEN_CAPTURE_OUTCOMES
    assert replay.requests == [_GOLDEN_REPLAY_REQUEST]
    # INVARIANT: the replay call keys the same digest the capture recorded, so it reads that entry.
    assert request_digest(replay.requests[0][2]) == _GOLDEN_DIGEST
    assert replay_tally.occurrences == {(_GOLDEN_CASE_KEY, "chat", _GOLDEN_DIGEST): 1}
    assert replay_tally.outcomes == []
    assert replay_tally.attributes() == {"capture.replay": "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"}
    assert recorder.reports() == _GOLDEN_REPLAY_REPORTS
