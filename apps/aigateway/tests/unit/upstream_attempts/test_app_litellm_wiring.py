"""The real Gateway counts LiteLLM sends into `X-AIGW-Upstream-Attempts` (contract C7).

# FEATURE: Router Recipe extension Unit 5.1, test-plan §4 item 8 — real `create_app`, real routes,
# real LiteLLM; only the physical transport is fake.
# INVARIANT: `refuse_unobserved_client` fails any LiteLLM send that bypasses the injected client,
# so every count below is an observation of the Gateway wiring, never a default `0`.
# INVARIANT: the count holds with usage accounting enabled and disabled; it never needs a
# collector.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core import retry
from aigateway.core.admission import QUEUE_HEADER
from aigateway.core.concurrency import _get_or_create_semaphore, effective_provider_limit

from .conftest import CHAT, HEADER, ROUTES, chat_body, connect, login, ok, respond
from .litellm_seam import ANTHROPIC_MESSAGE, FakeTransport, connect_error_then


@pytest.fixture(params=["accounting-on", "accounting-off"])
def accounting(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    enabled = request.param == "accounting-on"
    monkeypatch.setenv("AIGW_TAXONOMY_ENABLED", "true" if enabled else "false")
    return enabled


@pytest.fixture
def gateway(seam: FakeTransport, accounting: bool, client: TestClient) -> TestClient:
    del seam, accounting
    return connect(login(client))


def _chat(gateway: TestClient, provider: str, **extra: Any) -> httpx.Response:
    return gateway.post(CHAT, json=chat_body(provider, **extra))


@pytest.mark.parametrize("provider", ROUTES)
def test_one_send_is_one_attempt(gateway: TestClient, seam: FakeTransport, provider: str) -> None:
    respond(seam, ok(ROUTES[provider][1]))

    response = _chat(gateway, provider)

    assert response.status_code == 200, response.text
    assert len(seam.sent) == 1
    assert response.headers[HEADER] == "1"


@pytest.mark.parametrize("provider", ROUTES)
def test_litellm_s_hidden_resend_is_counted(
    gateway: TestClient, seam: FakeTransport, provider: str
) -> None:
    seam.respond = connect_error_then(ROUTES[provider][1])

    response = _chat(gateway, provider)

    assert response.status_code == 200, response.text
    assert len(seam.sent) == 2
    assert response.headers[HEADER] == "2"


def test_an_outer_overload_retry_is_another_send(gateway: TestClient, seam: FakeTransport) -> None:
    # WHY 429: the Gateway's overload retry, not LiteLLM, sends the second request.
    limited = httpx.Response(
        429,
        headers={"retry-after": "0"},
        json={"type": "error", "error": {"type": "rate_limit_error", "message": "busy"}},
    )
    respond(seam, lambda _request: limited, ok(ANTHROPIC_MESSAGE))

    response = _chat(gateway, "anthropic")

    assert response.status_code == 200, response.text
    assert len(seam.sent) == 2
    assert response.headers[HEADER] == "2"


def _overloaded(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        529,
        headers={"retry-after": "0"},
        json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}},
    )


# WHY HuggingFace and OpenRouter: LiteLLM hands the Gateway their 529 as a 529; it maps an
# Anthropic 529 to a 500, which the overload retry never retries.
OVERLOAD_ROUTES = ["huggingface", "openrouter"]


@pytest.mark.parametrize("provider", OVERLOAD_ROUTES)
def test_an_outer_529_retry_is_another_send(
    gateway: TestClient, seam: FakeTransport, provider: str
) -> None:
    respond(seam, _overloaded, ok(ROUTES[provider][1]))

    response = _chat(gateway, provider)

    assert response.status_code == 200, response.text
    assert len(seam.sent) == 2
    assert response.headers[HEADER] == "2"


@pytest.mark.parametrize("provider", OVERLOAD_ROUTES)
def test_without_the_outer_retry_the_same_529_is_one_send(
    gateway: TestClient, seam: FakeTransport, provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: proves the second send above is the Gateway's overload retry, not LiteLLM's own.
    monkeypatch.setattr(retry, "RETRYABLE_STATUS_CODES", frozenset({429, 503}))
    respond(seam, _overloaded, ok(ROUTES[provider][1]))

    response = _chat(gateway, provider)

    assert response.status_code >= 500, response.text
    assert len(seam.sent) == 1
    assert response.headers[HEADER] == "1"


def test_an_upstream_error_answer_counts_its_send(gateway: TestClient, seam: FakeTransport) -> None:
    respond(seam, lambda _request: httpx.Response(400, json={"error": {"message": "bad"}}))

    response = _chat(gateway, "huggingface")

    assert response.status_code >= 400
    assert len(seam.sent) == 1
    assert response.headers[HEADER] == "1"


def test_a_transport_failure_counts_the_uncertain_send(
    gateway: TestClient, seam: FakeTransport
) -> None:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    seam.respond = time_out

    response = _chat(gateway, "huggingface")

    assert response.status_code >= 500
    assert len(seam.sent) == 1
    assert response.headers[HEADER] == "1"


def test_a_malformed_body_is_zero(gateway: TestClient, seam: FakeTransport) -> None:
    response = _chat(gateway, "huggingface", messages="not a list")

    assert 400 <= response.status_code < 500, response.text
    assert seam.sent == []
    assert response.headers[HEADER] == "0"


def test_a_codec_refusal_before_any_send_is_zero(gateway: TestClient, seam: FakeTransport) -> None:
    # WHY: LiteLLM's Anthropic codec refuses an unknown content part while building the request,
    # so the call fails with no request ever admitted to the transport.
    response = _chat(
        gateway, "anthropic", messages=[{"role": "user", "content": [{"type": "nope"}]}]
    )

    assert response.status_code >= 400, response.text
    assert seam.sent == []
    assert response.headers[HEADER] == "0"


def test_an_unknown_provider_is_zero(gateway: TestClient, seam: FakeTransport) -> None:
    response = gateway.post(
        CHAT, json={"model": "nobody/model", "messages": [{"role": "user", "content": "hi"}]}
    )

    assert response.status_code == 400
    assert seam.sent == []
    assert response.headers[HEADER] == "0"


def test_a_streaming_chat_is_unchanged(gateway: TestClient, seam: FakeTransport) -> None:
    del seam
    response = _chat(gateway, "anthropic", stream=True)

    assert HEADER not in response.headers


def test_admission_shedding_is_zero(gateway: TestClient, seam: FakeTransport) -> None:
    # WHY every slot taken: the Gateway's own queue refuses the call before any send.
    app = cast(FastAPI, gateway.app)
    limit = effective_provider_limit(app.state.settings, "huggingface")
    slots = _get_or_create_semaphore(app, "huggingface", limit)
    while not slots.locked():
        asyncio.run(slots.acquire())

    response = gateway.post(CHAT, json=chat_body("huggingface"), headers={QUEUE_HEADER: "0.05"})

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "provider_queue_timeout"
    assert seam.sent == []
    assert response.headers[HEADER] == "0"
