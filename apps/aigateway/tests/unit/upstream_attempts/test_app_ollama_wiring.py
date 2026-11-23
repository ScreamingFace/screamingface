"""The real Gateway counts an Ollama chat's LiteLLM sends (contract C7, test-plan §4 item 8).

# FEATURE: Router Recipe extension Unit 5.1 — HuggingFace and Ollama pass the dispatched client to
# LiteLLM's base handler, so the real Gateway test must prove the attempt hook sees their sends.
# WHY a module of its own: Ollama takes no key, so it cannot join `ROUTES`, whose callers attach
# one key per entry. A fake model listing and the fake transport stand in for a live Ollama host.
# INVARIANT: `refuse_unobserved_client` fails any send that bypasses the injected client, so each
# count below observes the route's own injection, never a default `0`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.plugins.ollama_provider import plugin as ollama_plugin
from aigateway.plugins.ollama_provider.discovery import DEFAULT_OLLAMA_HOST

from .conftest import CHAT, HEADER, login, ok, respond
from .litellm_seam import OLLAMA_CHAT, OLLAMA_MODEL, FakeTransport, connect_error_then


@pytest.fixture(params=["accounting-on", "accounting-off"])
def accounting(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    enabled = request.param == "accounting-on"
    monkeypatch.setenv("AIGW_TAXONOMY_ENABLED", "true" if enabled else "false")


@pytest.fixture
def ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY before the app: the catalog lists the host's installed models when the app starts.
    # WHY the loopback default: a remote host needs the separate allow-remote switch, and the fake
    # transport answers every send, so no request reaches a real Ollama on this machine.
    monkeypatch.setenv("AIGW_OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
    installed = OLLAMA_MODEL.split("/", 1)[1]
    monkeypatch.setattr(ollama_plugin, "discover_ollama_models", lambda _host: [installed])


@pytest.fixture
def gateway(seam: FakeTransport, accounting: None, ollama: None, client: TestClient) -> TestClient:
    del seam, accounting, ollama
    return login(client)


def _chat(gateway: TestClient, **extra: Any) -> httpx.Response:
    body = {"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": "hello"}], **extra}
    return gateway.post(CHAT, json=body)


def test_one_ollama_send_is_one_attempt(gateway: TestClient, seam: FakeTransport) -> None:
    respond(seam, ok(OLLAMA_CHAT))

    response = _chat(gateway)

    assert response.status_code == 200, response.text
    assert [str(request.url) for request in seam.sent] == [f"{DEFAULT_OLLAMA_HOST}/api/chat"]
    assert response.headers[HEADER] == "1"


def test_litellm_s_hidden_ollama_resend_is_counted(
    gateway: TestClient, seam: FakeTransport
) -> None:
    seam.respond = connect_error_then(OLLAMA_CHAT)

    response = _chat(gateway)

    assert response.status_code == 200, response.text
    assert len(seam.sent) == 2
    assert response.headers[HEADER] == "2"
