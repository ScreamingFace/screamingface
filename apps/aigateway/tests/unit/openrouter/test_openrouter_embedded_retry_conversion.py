"""Real-conversion regression: embedded choice-level errors stay non-retryable.

`test_openrouter_embedded_retry.py` pins the retry boundary with a synthetic
top-level ``error`` payload — but through REAL litellm 1.87.0 a meaningful
top-level error never reaches the plugin scan (the converter raises first, and
the mapped exception follows the transport path). The production-reachable
embedded path is the CHOICE level: litellm relocates ``choices[].error`` into
``provider_specific_fields.error`` and normalizes ``finish_reason: "error"``
to ``"stop"`` (keeping ``native_finish_reason: "error"``).

This file drives raw OpenRouter bodies through the real
``convert_to_model_response_object`` and returns the resulting
``ModelResponse`` from mocked ``acompletion``, pinning on the reachable path:
exactly one upstream call per embedded 429/503/529, the sanitized
status/code mapping, no invented Retry-After, and choice-level 401
invalidating the effective connection (CODE-2, plan D7/D9).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from litellm.litellm_core_utils.llm_response_utils.convert_dict_to_response import (
    convert_to_model_response_object,
)
from litellm.types.utils import ModelResponse

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-conv"
_MODEL = "openrouter/anthropic/claude-fable-5"


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


@pytest.fixture()
def fast_retries(authenticated_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero out backoff/jitter so a retry regression fails fast instead of
    sleeping; the call COUNT under test is unaffected."""
    settings = authenticated_client.app.state.settings
    monkeypatch.setattr(settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(settings, "retry_jitter_seconds", 0.0)


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _create_connection(client, label: str) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": label, "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


def _active_labels(client, account_id: str) -> list[str]:
    async def _list() -> list[str]:
        connections = await OAuthConnectionStore().list(
            account_id, provider="openrouter", status="active"
        )
        return sorted(connection.label for connection in connections)

    return client.portal.call(_list)


def _post_chat(client, *, profile: str | None = None):
    headers = {"X-Profile": profile} if profile is not None else {}
    return client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )


def _raw_openrouter_choice_error(status: int) -> dict[str, Any]:
    """The real OpenRouter non-streaming embedded-error shape: the error rides
    inside the choice alongside partial output, with finish_reason "error"."""
    return {
        "id": f"gen-conv-{status}",
        "created": 1,
        "model": "anthropic/claude-fable-5",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "partial output"},
                "finish_reason": "error",
                "error": {"code": status, "message": "Provider returned error"},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _really_converted(raw: dict[str, Any]) -> ModelResponse:
    converted = convert_to_model_response_object(
        response_object=raw,
        model_response_object=ModelResponse(),
        response_type="completion",
        stream=False,
    )
    # Narrow litellm's union return: non-streaming "completion" always yields
    # a ModelResponse.
    assert isinstance(converted, ModelResponse)
    return converted


def _counting_converted_acompletion(raw: dict[str, Any], calls: dict):
    async def fake_acompletion(**_kwargs):
        calls["n"] += 1
        # A fresh, genuinely-converted ModelResponse per upstream attempt —
        # exactly what litellm.acompletion hands the plugin in production.
        return _really_converted(raw)

    return fake_acompletion


def test_real_conversion_relocates_choice_error_and_masks_finish_reason() -> None:
    """Premise pin: if a litellm upgrade stops relocating choices[].error into
    provider_specific_fields (or stops masking finish_reason "error" as
    "stop"), the retry tests below would silently test the wrong path — fail
    loudly here instead."""
    dumped = _really_converted(_raw_openrouter_choice_error(429)).model_dump()
    choice = dumped["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert "error" not in choice
    fields = choice["provider_specific_fields"]
    assert fields["error"] == {"code": 429, "message": "Provider returned error"}
    assert fields["native_finish_reason"] == "error"


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(429, "rate_limited"), (503, "provider_unavailable"), (529, "provider_unavailable")],
)
def test_embedded_choice_error_via_real_conversion_makes_exactly_one_call(
    enabled_openrouter,
    fast_retries,
    credential_blobs,
    authenticated_client,
    status: int,
    expected_code: str,
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    raw = _raw_openrouter_choice_error(status)
    with patch("litellm.acompletion", _counting_converted_acompletion(raw, calls)):
        resp = _post_chat(authenticated_client)

    # INVARIANT (CODE-2): the upstream call already returned this payload —
    # an embedded 429/503/529 must make exactly one upstream call.
    assert calls["n"] == 1
    assert resp.status_code == status
    assert resp.json()["detail"]["code"] == expected_code
    # Sanitized: raw provider text never echoes; no Retry-After is invented.
    assert "Provider returned error" not in resp.text
    assert "retry-after" not in resp.headers
    assert _active_labels(authenticated_client, account_id) == ["work-or"]


def test_embedded_choice_401_via_real_conversion_invalidates_effective_connection(
    enabled_openrouter, fast_retries, credential_blobs, authenticated_client
) -> None:
    account_id = _account_id(authenticated_client)
    _create_connection(authenticated_client, "work-or")

    calls = {"n": 0}
    raw = _raw_openrouter_choice_error(401)
    with patch("litellm.acompletion", _counting_converted_acompletion(raw, calls)):
        resp = _post_chat(authenticated_client)

    assert calls["n"] == 1
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "auth_required"
    # D9 local: the effective connection flips to error.
    assert _active_labels(authenticated_client, account_id) == []
