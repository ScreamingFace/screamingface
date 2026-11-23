"""The attempt header agrees with usage accounting (contract C7, test-plan §4 item 9).

# FEATURE: Router Recipe extension Unit 5.1 — both observe the same physical sends through the
# same hooks, so when accounting renders every attempt the header equals the sum, over attempts,
# of one send plus its redirect hops.
# INVARIANT: accounting folds a followed redirect into one attempt; the header counts each hop,
# because each hop is a request the Gateway sent upstream.
# INVARIANT: the header never depends on the accounting response bound; an attempt accounting
# omits from the body is still counted.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.plugins.taxonomy import render

from .conftest import CHAT, HEADER, ROUTES, chat_body, connect, login, ok, respond
from .litellm_seam import FakeTransport, connect_error_then

PROVIDERS = ["anthropic", "openrouter"]


@pytest.fixture
def accounting_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_TAXONOMY_ENABLED", "true")


@pytest.fixture
def gateway(seam: FakeTransport, accounting_on: None, client: TestClient) -> TestClient:
    del seam, accounting_on
    return connect(login(client))


def _accounting(response: httpx.Response) -> dict[str, Any]:
    return response.json()[render.METADATA_KEY]["usage_accounting"]


def _sends_by_accounting(accounting: dict[str, Any]) -> int:
    assert accounting["omitted_attempts"] == 0
    return sum(1 + attempt["redirect_hop_count"] for attempt in accounting["attempts"])


def _redirect_once(payload: dict[str, Any]) -> Any:
    sent = {"n": 0}

    def answer(request: httpx.Request) -> httpx.Response:
        sent["n"] += 1
        if sent["n"] == 1:
            moved = request.url.copy_with(host="elsewhere.example")
            return httpx.Response(307, headers={"location": str(moved)})
        return httpx.Response(200, json=payload)

    return answer


@pytest.mark.parametrize("provider", PROVIDERS)
def test_one_send_agrees(gateway: TestClient, seam: FakeTransport, provider: str) -> None:
    respond(seam, ok(ROUTES[provider][1]))

    response = gateway.post(CHAT, json=chat_body(provider))

    assert response.status_code == 200, response.text
    accounting = _accounting(response)
    assert accounting["observed_attempts"] == 1
    assert response.headers[HEADER] == str(_sends_by_accounting(accounting)) == "1"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_hidden_resend_agrees(gateway: TestClient, seam: FakeTransport, provider: str) -> None:
    seam.respond = connect_error_then(ROUTES[provider][1])

    response = gateway.post(CHAT, json=chat_body(provider))

    assert response.status_code == 200, response.text
    accounting = _accounting(response)
    assert accounting["observed_attempts"] == 2
    assert response.headers[HEADER] == str(_sends_by_accounting(accounting)) == "2"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_followed_redirect_is_one_attempt_and_two_sends(
    gateway: TestClient, seam: FakeTransport, provider: str
) -> None:
    seam.respond = _redirect_once(ROUTES[provider][1])

    response = gateway.post(CHAT, json=chat_body(provider))

    assert response.status_code == 200, response.text
    assert [request.url.host for request in seam.sent][1] == "elsewhere.example"
    accounting = _accounting(response)
    assert accounting["observed_attempts"] == 1
    assert [attempt["redirect_hop_count"] for attempt in accounting["attempts"]] == [1]
    assert response.headers[HEADER] == str(_sends_by_accounting(accounting)) == "2"


def test_an_attempt_accounting_omits_is_still_counted(
    gateway: TestClient, seam: FakeTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "MAX_RENDERED_ATTEMPTS", 1)
    seam.respond = connect_error_then(ROUTES["openrouter"][1])

    response = gateway.post(CHAT, json=chat_body("openrouter"))

    assert response.status_code == 200, response.text
    accounting = _accounting(response)
    assert (accounting["observed_attempts"], accounting["rendered_attempts"]) == (2, 1)
    assert accounting["omitted_attempts"] == 1
    assert accounting["capture_status"] == "partial"
    assert len(seam.sent) == 2
    assert response.headers[HEADER] == "2"
