"""Characterization tests for the gateway round trip, written before the move.

FEATURE: shared gateway round trip (PRD `gateway-transport.md`, GT-S1, GT-S2, GT-S3). The round
trip of one model call (`_logged_round_trip` down to `_raise_for_status`) moves out of
`world/connector.py` into `world/gateway_transport.py`, and no function body changes. These tests
pin what that code does today: the outbound headers, the request body and its digest, the error
code and the retry count of each gateway reply class, and the usage records.

INVARIANT: each golden is a literal recorded from the code of today. A move that changes one of
them changes behaviour. Do not regenerate a golden to make the move pass.

AIDEV-NOTE: the tests drive the production endpoint (`build_aigateway_world` and url4 `run`)
through the shared fake gateway of `frozen_copy_support`, never a private helper. The only private
`connector` name is in `_no_waits`: after the move, retarget that one line.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    COPY,
    MODEL,
    Gateway,
    capture_scope,
    chat,
    error,
    run_call,
    stored,
)

from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.capture_outcomes import CaptureTally, capture_outcomes, request_digest
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.trace_scope import run_trace_scope
from screamingface_engine.world import gateway_transport
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.observe import ModelResponse, ObservationEvent, Usage
from url4.streaming.interfaces import TraceContext
from url4.streaming.protocol import CachePolicy

# WHY distinct values: the two time-out headers must not be told apart by luck.
_CONFIG = AigatewayConfig(
    models=(ModelSpec(id=MODEL, web_search=False),),
    default_model=MODEL,
    timeout_s=45.0,
    queue_timeout_s=15.0,
)
_TRACE = TraceContext(trace_id="0af7651916cd43dd8448eb211c80319c", root_span_id="b7ad6b7169203331")
# WHY `X-Profile` too: it is not a forwarded identity header, so the golden shows it is dropped.
_IDENTITY = {"X-User-Email": "golden@x.test", "X-Profile": "not-forwarded"}
_EXPRESSION = f"/{MODEL}?temperature=0.25&max_tokens=64&q=('the context')!'the intent'"
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


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero every retry wait: the transport back-off and the Candidate-call wait.

    AIDEV-NOTE: the ONE private `connector` name in this file. After the move, patch it on
    `gateway_transport` instead.
    """

    async def no_wait(_attempt: int, _delay: float) -> None:
        return None

    monkeypatch.setattr(gateway_transport, "_wait_to_retry", no_wait)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    def reports(self) -> list[Usage | ModelResponse]:
        """The usage and response records, with the span id cleared.

        WHY cleared: url4 mints a random span id per run. It is not part of what the round trip
        reports, so the golden leaves it out.
        """
        return [
            dataclasses.replace(event, span_id=None)
            for event in self.events
            if isinstance(event, Usage | ModelResponse)
        ]


async def _call(
    gateway: Gateway, scope: RequestScope, *, capture: bool
) -> tuple[CaptureTally, str | None]:
    """One model call through the production endpoint of `_CONFIG`, with a fixed trace.

    `capture` plays the executor's capture binding: the tally is in capture mode with `COPY`.
    """
    async with gateway.client() as client:
        world = await build_aigateway_world(_CONFIG, client=client)
        with run_trace_scope(_TRACE), request_scope(scope), capture_outcomes() as tally:
            if capture:
                tally.mode, tally.frozen_copy_id = "capture", COPY
            answer = await url4_run(_EXPRESSION, io=world.node)
    return tally, answer


def _engine_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name.lower(): value
        for name, value in headers.items()
        if name.lower() not in _HTTPX_OWN_HEADERS
    }


# ── GT-1: the outbound headers ─────────────────────────────────────────────────────────────

_GOLDEN_HEADERS = {
    "x-user-email": "golden@x.test",
    "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    "x-aigw-execution-timeout-s": "45.0",
    "x-aigw-queue-timeout-s": "15.0",
}
_GOLDEN_CAPTURE_HEADERS = {
    **_GOLDEN_HEADERS,
    "x-aigw-frozen-copy": "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11",
    "x-aigw-case-key": "2263cb2c1cc646471e16983da2568976",
    "x-aigw-call-occurrence": "0",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capture", "golden"),
    [(False, _GOLDEN_HEADERS), (True, _GOLDEN_CAPTURE_HEADERS)],
    ids=["normal", "capture"],
)
async def test_headers_for_fixed_scope_match_golden(capture: bool, golden: dict[str, str]) -> None:
    """GT-1: a fixed request scope sends exactly the golden Engine-owned headers."""
    gateway = Gateway([chat("ok", stored())])
    scope = RequestScope(
        origin="run",
        identity_headers=_IDENTITY,
        answer_seed=7,
        cache=CachePolicy(participate=False),
        capture=capture,
    )

    with case_scope(7):
        _tally, answer = await _call(gateway, scope, capture=capture)

    assert answer == "ok"
    ((headers, _body),) = gateway.calls(CHAT)
    assert _engine_headers(headers) == golden


# ── GT-2: the request body and its digest ──────────────────────────────────────────────────

_GOLDEN_BODY_BYTES = (
    b'{"model":"anthropic/claude-haiku-4-5","messages":[{"role":"system","content":"the intent"},'
    b'{"role":"user","content":"the context"}],"temperature":0.25,"max_tokens":64,'
    b'"cache":{"use-cache":false}}'
)
_GOLDEN_BODY_SHA256 = "8a50710d8e472c974d1508aba7971aca0ea94bbb3b4b64bcfd694c2789f68e67"
_GOLDEN_BODY = {
    "model": "anthropic/claude-haiku-4-5",
    "messages": [
        {"role": "system", "content": "the intent"},
        {"role": "user", "content": "the context"},
    ],
    "temperature": 0.25,
    "max_tokens": 64,
    "cache": {"use-cache": False},
}
_GOLDEN_SENT_DIGEST = "719ad2fae830c956fe0bc56fcaad43f1b4d14114ce878d36d289327a7a9cf59f"
# INVARIANT: the capture digest is of the body BEFORE the cache field is merged in, so it is not
# the digest of the sent bytes. Both are pinned.
_GOLDEN_RECORDED_DIGEST = "7b24d5677bffa8b68496e2cca3651ad9e7150db5698fcc776a3cf3fb69112fc6"


@pytest.mark.asyncio
async def test_model_call_body_digest_matches_golden() -> None:
    """GT-2: a fixed call sends the golden body bytes, and its digests match the goldens."""
    gateway = Gateway([chat("ok", stored())])
    sent: list[bytes] = []

    async def keep_bytes(request: httpx.Request) -> None:
        sent.append(request.content)

    gateway.gate = keep_bytes
    scope = capture_scope(cache=CachePolicy(participate=False))

    with case_scope(7):
        tally, answer = await _call(gateway, scope, capture=True)

    assert answer == "ok"
    assert sent == [_GOLDEN_BODY_BYTES]
    assert hashlib.sha256(sent[0]).hexdigest() == _GOLDEN_BODY_SHA256
    assert json.loads(sent[0]) == _GOLDEN_BODY
    assert request_digest(json.loads(sent[0])) == _GOLDEN_SENT_DIGEST
    assert [o.digest for o in tally.outcomes] == [_GOLDEN_RECORDED_DIGEST]


# ── GT-3: each reply class → error code, permanence and HTTP attempts ──────────────────────

_Step = httpx.Response | BaseException


def _status(status: int) -> httpx.Response:
    """A gateway failure whose detail names no code, so the Engine's own code applies."""
    return httpx.Response(status, json={"detail": {"message": "m"}})


_REPLIES: dict[str, Callable[[], list[_Step]]] = {
    "200": lambda: [chat("ok")],
    "302": lambda: [httpx.Response(302, headers={"Location": "http://login.test/"})],
    "400": lambda: [_status(400)],
    "401": lambda: [_status(401)],
    "404": lambda: [_status(404)],
    "429": lambda: [_status(429)],
    "500": lambda: [_status(500)],
    "503": lambda: [_status(503)],
    "503-queue": lambda: [error(503, "provider_queue_timeout")],
    "429-then-200": lambda: [_status(429), chat("ok")],
    "non-json-200": lambda: [httpx.Response(200, content=b"<html>login</html>")],
    "empty-200": lambda: [httpx.Response(200, content=b"")],
    "no-choices-200": lambda: [
        httpx.Response(200, json={"choices": [], "usage": {"prompt_tokens": 1}})
    ],
    "read-error": lambda: [httpx.ReadError("lost")],
    "connect-error": lambda: [httpx.ConnectError("down")],
    "read-error-then-200": lambda: [httpx.ReadError("lost"), chat("ok")],
}

# (reply, Candidate call, (answer, (code, permanent) or None, HTTP attempts the gateway saw))
_TABLE: list[tuple[str, bool, tuple[str | None, tuple[str, bool] | None, int]]] = [
    # A call outside a Candidate invocation: only the transport retry applies.
    ("200", False, ("ok", None, 1)),
    ("302", False, (None, ("aigateway_bad_response", True), 1)),
    ("400", False, (None, ("aigateway_http_400", True), 1)),
    ("401", False, (None, ("aigateway_http_401", True), 1)),
    ("404", False, (None, ("aigateway_http_404", True), 1)),
    ("429", False, (None, ("aigateway_http_429", False), 1)),
    ("500", False, (None, ("aigateway_http_500", False), 1)),
    ("503", False, (None, ("aigateway_http_503", False), 1)),
    ("503-queue", False, (None, ("provider_queue_timeout", False), 2)),
    ("429-then-200", False, (None, ("aigateway_http_429", False), 1)),
    ("non-json-200", False, (None, ("aigateway_bad_response", True), 1)),
    ("empty-200", False, (None, ("aigateway_empty_response", False), 1)),
    ("no-choices-200", False, (None, ("aigateway_bad_response", True), 1)),
    ("read-error", False, (None, ("aigateway_transport_error", False), 2)),
    ("connect-error", False, (None, ("aigateway_transport_error", False), 2)),
    ("read-error-then-200", False, ("ok", None, 2)),
    # A Candidate call: the Candidate retry on 429 and 5xx applies on top.
    ("200", True, ("ok", None, 1)),
    ("400", True, (None, ("aigateway_http_400", True), 1)),
    ("429", True, (None, ("aigateway_http_429", False), 3)),
    ("500", True, (None, ("aigateway_http_500", False), 3)),
    ("503", True, (None, ("aigateway_http_503", False), 3)),
    ("503-queue", True, (None, ("provider_queue_timeout", False), 6)),
    ("429-then-200", True, ("ok", None, 2)),
    ("empty-200", True, (None, ("aigateway_empty_response", False), 1)),
    ("read-error", True, (None, ("aigateway_transport_error", False), 2)),
    ("connect-error", True, (None, ("aigateway_transport_error", False), 2)),
]


async def _outcome(
    gateway: Gateway, *, candidate: bool
) -> tuple[str | None, ResolutionError | None]:
    scope = RequestScope(origin="run")
    if not candidate:
        _tally, answer, failure = await run_call(gateway, scope, web_search=False)
        return answer, failure
    with candidate_invocation_scope():
        _tally, answer, failure = await run_call(gateway, scope, web_search=False)
    return answer, failure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "candidate", "expected"),
    _TABLE,
    ids=[f"{reply}-{'candidate' if candidate else 'other'}" for reply, candidate, _ in _TABLE],
)
async def test_status_classes_map_to_same_error_codes_and_retries(
    reply: str, candidate: bool, expected: tuple[str | None, tuple[str, bool] | None, int]
) -> None:
    """GT-3: each gateway reply class maps to the golden error code, permanence and attempts."""
    gateway = Gateway(_REPLIES[reply]())

    answer, failure = await _outcome(gateway, candidate=candidate)

    error_class = None if failure is None else (failure.code, failure.permanent)
    assert (answer, error_class, len(gateway.calls(CHAT))) == expected


# ── GT-4: the usage and response records ───────────────────────────────────────────────────

_PRICED_AIGW: dict[str, Any] = {
    "usage_accounting": {
        "capture_status": "complete",
        "cache": {"status": "miss", "reference": None},
        "attempts": [
            {
                "provider": "openrouter",
                "response_model": "anthropic/claude-haiku-4-5-20251001",
                "outcome": "succeeded",
                "usage": {
                    "input": {"total": 11, "cache_read": 3, "cache_write": 2},
                    "output": {"total": 7, "reasoning": 4},
                },
            }
        ],
    },
    "request_economics": {
        "direct_cost_status": "complete",
        "known_direct_cost_subtotals": [
            {"amount": "0.00125", "unit": "openrouter_credits", "source": "openrouter"}
        ],
    },
}
_CACHED_AIGW: dict[str, Any] = {
    "usage_accounting": {
        "capture_status": "complete",
        "cache": {
            "status": "hit",
            "reference": {
                "direct_cost": {
                    "status": "reported",
                    "amount": "0.002",
                    "unit": "openrouter_credits",
                    "source": "openrouter.usage.cost",
                }
            },
        },
        "attempts": [],
    },
    "request_economics": {
        "direct_cost_status": "not_applicable",
        "known_direct_cost_subtotals": [],
    },
}


def _reply(aigw: dict[str, Any] | None, headers: dict[str, str]) -> httpx.Response:
    body: dict[str, Any] = {
        "choices": [
            {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": 651,
            "completion_tokens": 25,
            "prompt_tokens_details": {"image_and_file_tokens": 0},
        },
    }
    if aigw is not None:
        body["_aigw"] = aigw
    return httpx.Response(200, headers=headers, json=body)


def _usage_case(name: str) -> tuple[httpx.Response, list[Usage | ModelResponse]]:
    """The gateway reply of one case and the golden records the Engine reports for it."""
    if name == "priced":
        return _reply(_PRICED_AIGW, {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "absent"}), [
            Usage(
                span_id=None,
                provider="openrouter",
                model=MODEL,
                input_tokens=11,
                output_tokens=7,
                response_model="anthropic/claude-haiku-4-5-20251001",
                cache_read_tokens=3,
                cache_creation_tokens=2,
                reasoning_tokens=4,
                cost_usd=Decimal("0.00125"),
                image_and_file_tokens=0,
            ),
            ModelResponse(
                span_id=None,
                finish_reason="stop",
                refusal=None,
                cache_status="miss",
                cache_reason="absent",
            ),
        ]
    if name == "unpriced":
        return _reply(None, {}), [
            Usage(
                span_id=None,
                provider="anthropic",
                model=MODEL,
                input_tokens=651,
                output_tokens=25,
                response_model=None,
                cost_usd=None,
                image_and_file_tokens=0,
            ),
            ModelResponse(span_id=None, finish_reason="stop", refusal=None),
        ]
    return _reply(_CACHED_AIGW, {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}), [
        Usage(
            span_id=None,
            provider="anthropic",
            model=MODEL,
            input_tokens=0,
            output_tokens=0,
            response_model=None,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=0,
            cost_usd=Decimal("0"),
            image_and_file_tokens=None,
        ),
        ModelResponse(
            span_id=None,
            finish_reason="stop",
            refusal=None,
            cache_status="hit",
            cache_reason="fresh",
            cache_saved_cost_usd=Decimal("0.002"),
            cache_saved_cost_provenance="reported",
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["priced", "unpriced", "cached"])
async def test_usage_report_for_priced_unpriced_cached_matches_golden(name: str) -> None:
    """GT-4: priced, unpriced and cached replies report the golden usage and response records."""
    reply, golden = _usage_case(name)
    recorder = _Recorder()

    _tally, answer, failure = await run_call(
        Gateway([reply]), RequestScope(origin="run"), web_search=False, observer=recorder
    )

    assert (answer, failure) == ("an answer", None)
    assert recorder.reports() == golden
