"""OpenRouter BYOK is isolated from LiteLLM's orchestration control plane."""

from __future__ import annotations

from collections import UserDict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import litellm
import pytest
from litellm.caching.caching import Cache
from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER
from litellm.types.utils import CredentialItem

from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-control-plane"
_MODEL = "openrouter/anthropic/claude-fable-5"


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _create_connection(client) -> None:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "isolated-openrouter", "api_key": _KEY},
    )
    assert response.status_code == 201, response.text


def _request(client, **overrides):
    body = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        **overrides,
    }
    return client.post(
        "/v1/chat/completions",
        json=body,
    )


def _successful_acompletion(captured: dict | None = None):
    async def fake_acompletion(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-isolated",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )

    return fake_acompletion


def _wire_response(request: httpx.Request, generation_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": generation_id,
            "model": "anthropic/claude-fable-5",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        request=request,
    )


def test_litellm_orchestration_controls_never_reach_dispatch(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}
    controls = {
        "litellm_credential_name": "attacker-credential",
        "guardrails": ["attacker-guardrail"],
        "guardrail_config": {"mode": "attacker"},
        "disable_global_guardrails": True,
        "prompt_id": "attacker-prompt",
        "prompt_variables": {"secret": "attacker"},
        "prompt_label": "attacker-label",
        "prompt_version": 7,
        "caching": True,
        "cache_key": "shared-attacker-key",
        "preset_cache_key": "shared-attacker-preset",
    }
    metadata = {
        "trace_id": "safe-trace",
        "guardrails": ["attacker-guardrail"],
        "disable_global_guardrails": True,
        "requester_metadata": {
            "disable_global_guardrails": True,
            "guardrails": ["attacker-guardrail"],
            "tenant": "safe-tenant",
        },
        "user_api_key_metadata": {
            "disable_global_guardrails": True,
            "guardrails": ["attacker-guardrail"],
            "team": "safe-team",
        },
        "previous_models": [{"model": "attacker-fallback"}],
    }

    with patch("litellm.acompletion", _successful_acompletion(captured)):
        response = _request(authenticated_client, **controls, metadata=metadata)

    assert response.status_code == 200, response.text
    for field in controls.keys() - {"caching"}:
        assert field not in captured
    assert captured["caching"] is False
    assert captured["metadata"] == {
        "trace_id": "safe-trace",
        "requester_metadata": {"tenant": "safe-tenant"},
        "user_api_key_metadata": {"team": "safe-team"},
    }


def test_openrouter_pins_tls_and_disables_litellm_cache(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}

    with patch("litellm.acompletion", _successful_acompletion(captured)):
        response = _request(authenticated_client)

    assert response.status_code == 200, response.text
    assert captured["ssl_verify"] is True
    assert captured["caching"] is False
    assert captured["cache"] == {"no-cache": True, "no-store": True}


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("model_alias_map", {_MODEL: "replicate/attacker/model"}),
        ("model_alias_map", UserDict({_MODEL: "replicate/attacker/model"})),
        ("model_fallbacks", [{_MODEL: ["replicate/attacker/model"]}]),
        ("callbacks", [object()]),
        ("input_callback", [object()]),
        ("success_callback", ["attacker-callback"]),
        ("failure_callback", ["attacker-callback"]),
        ("_async_input_callback", [object()]),
        ("_async_success_callback", [object()]),
        ("_async_failure_callback", [object()]),
        ("pre_call_rules", [object()]),
        ("post_call_rules", [object()]),
    ],
)
def test_unsafe_global_state_fails_closed_before_dispatch(
    enabled_openrouter,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: object,
) -> None:
    _create_connection(authenticated_client)
    monkeypatch.setattr(litellm, attribute, value)
    dispatch = AsyncMock(side_effect=AssertionError("upstream dispatch must not run"))

    with patch("litellm.acompletion", dispatch):
        response = _request(authenticated_client)

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "provider_unavailable",
        "message": "OpenRouter dispatch is unavailable",
    }
    assert response.json()["_aigw"]["usage_accounting"]["schema"] == "aigw.chat_usage_accounting"
    assert _KEY not in response.text
    dispatch.assert_not_awaited()


def test_unrelated_global_alias_does_not_block_openrouter(
    enabled_openrouter,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_connection(authenticated_client)
    monkeypatch.setattr(litellm, "model_alias_map", {"anthropic/unrelated": "other/model"})

    with patch("litellm.acompletion", _successful_acompletion()):
        response = _request(authenticated_client)

    assert response.status_code == 200, response.text


def test_named_credential_cannot_override_real_litellm_wire_destination(
    enabled_openrouter,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_connection(authenticated_client)
    monkeypatch.setattr(
        litellm,
        "credential_list",
        [
            CredentialItem(
                credential_name="attacker-credential",
                credential_info={},
                credential_values={
                    "api_key": "attacker-key",
                    "base_url": "https://attacker.invalid/v1",
                },
            )
        ],
    )
    captured: list[httpx.Request] = []

    async def fake_send(self, request, *args, **kwargs):  # noqa: ANN001
        captured.append(request)
        return _wire_response(request, "gen-official-destination")

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    monkeypatch.setenv("SSL_VERIFY", "False")
    try:
        response = _request(
            authenticated_client,
            litellm_credential_name="attacker-credential",
        )
        assert response.status_code == 200, response.text
        assert len(captured) == 1
        wire_request = captured[0]
        assert wire_request.url.host == "openrouter.ai"
        assert wire_request.url.path == "/api/v1/chat/completions"
        assert wire_request.headers["authorization"] == f"Bearer {_KEY}"
        assert "attacker" not in str(wire_request.url)
        assert "attacker-key" not in str(dict(wire_request.headers))
    finally:
        authenticated_client.portal.call(GLOBAL_LOGGING_WORKER.flush)


def test_global_litellm_cache_is_bypassed_on_real_completion_path(
    enabled_openrouter,
    credential_blobs,
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_connection(authenticated_client)
    callback_fields = (
        "callbacks",
        "input_callback",
        "success_callback",
        "failure_callback",
        "_async_input_callback",
        "_async_success_callback",
        "_async_failure_callback",
    )
    callback_snapshots = {field: list(getattr(litellm, field)) for field in callback_fields}
    monkeypatch.setattr(litellm, "cache", Cache())
    calls = 0

    async def fake_send(self, request, *args, **kwargs):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return _wire_response(request, f"gen-wire-{calls}")

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    try:
        first = _request(authenticated_client)
        second = _request(authenticated_client)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert calls == 2
        assert first.json()["id"] == "gen-wire-1"
        assert second.json()["id"] == "gen-wire-2"
    finally:
        authenticated_client.portal.call(GLOBAL_LOGGING_WORKER.flush)
        for field, snapshot in callback_snapshots.items():
            getattr(litellm, field)[:] = snapshot
