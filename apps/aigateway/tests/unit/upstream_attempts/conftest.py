"""Shared arrangement for the attempt-header app tests (contract C7).

# WHY a package conftest: the LiteLLM wiring and the accounting-agreement suites drive the same
# real app with the same fake transport; one arrangement keeps their observations comparable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.plugins.openrouter_provider import plugin as openrouter_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

from .litellm_seam import (
    ANTHROPIC_MESSAGE,
    HF_MODEL,
    OPENAI_COMPLETION,
    FakeTransport,
    install_fake_transport,
    quiet_litellm,
    refuse_unobserved_client,
)

HEADER = "x-aigw-upstream-attempts"
CHAT = "/v1/chat/completions"
ROUTES = {
    "huggingface": (HF_MODEL, OPENAI_COMPLETION),
    "anthropic": ("anthropic/claude-sonnet-4-5", ANTHROPIC_MESSAGE),
    "openrouter": ("openrouter/anthropic/claude-fable-5", OPENAI_COMPLETION),
}


@pytest.fixture(autouse=True)
def _valid_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Key readiness is not what these tests exercise, and it must not dial a provider.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: str, _api_key: str) -> Any:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture
def seam(monkeypatch: pytest.MonkeyPatch) -> FakeTransport:
    # WHY before the app: the lifespan builds the app-lifetime handlers, so their transport must
    # already be the fake one.
    quiet_litellm(monkeypatch)
    refuse_unobserved_client(monkeypatch)
    monkeypatch.setenv("AIGW_RETRY_BACKOFF_BASE", "0")
    monkeypatch.setenv("AIGW_RETRY_JITTER", "0")
    monkeypatch.setattr(
        openrouter_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    return install_fake_transport(monkeypatch)


def connect(client: TestClient, *, prefix: str = "") -> TestClient:
    """Attach one API key per LiteLLM provider in ``ROUTES`` for the caller."""
    for provider in ROUTES:
        created = client.post(
            f"{prefix}/v1/oauth/connections/api-key",
            json={"provider": provider, "label": f"{provider}-key", "api_key": f"{provider}-k"},
        )
        assert created.status_code == 201, created.text
    return client


def login(client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


def chat_body(provider: str, **extra: Any) -> dict[str, Any]:
    model, _payload = ROUTES[provider]
    return {"model": model, "messages": [{"role": "user", "content": "hello"}], **extra}


def respond(seam: FakeTransport, *steps: Callable[[httpx.Request], httpx.Response]) -> None:
    """Answer each send with the next step; the last step answers every later send."""
    queue = list(steps)
    seam.respond = lambda request: queue.pop(0)(request) if len(queue) > 1 else queue[0](request)


def ok(payload: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(200, json=payload)
