"""Shared chat-ingress hardening (OME-428 Phase 3, plan D6).

Mode-independent and provider-neutral: the /v1/chat/completions ingress strips
the known LiteLLM control plane for EVERY provider and validates untrusted
body shapes so malformed input can never produce a route-level 500. The HTTP
tests exercise the anthropic path on purpose — the hardening must not be
OpenRouter-specific.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from litellm.litellm_core_utils import initialize_dynamic_callback_params

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.request_hardening import (
    DISPATCH_CONTROL_FIELDS,
    chat_body_shape_error,
    strip_dispatch_controls,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

# The D6 control plane: the implementation plan's verbatim list plus the SEC-1
# review extension (azure/text_completion/atext_completion mode-flip flags).
# Pinned exactly so an accidental addition or removal shows up as a test diff.
_D6_CONTROL_FIELDS = {
    "api_key",
    "api_base",
    "base_url",
    "headers",
    "extra_headers",
    "model_list",
    "fallbacks",
    "context_window_fallbacks",
    "context_window_fallback_dict",
    "content_policy_fallbacks",
    "extra_body",
    "drop_params",
    "additional_drop_params",
    "use_litellm_proxy",
    "custom_llm_provider",
    "deployment_id",
    "ssl_verify",
    "max_retries",
    "num_retries",
    "cooldown_time",
    "no-log",
    "mock_response",
    "mock_tool_calls",
    "mock_timeout",
    "mock_delay",
    "provider_specific_header",
    "input_cost_per_token",
    "output_cost_per_token",
    "input_cost_per_second",
    "output_cost_per_second",
    # SEC-1: provider/mode-flip flags (litellm 1.87.0 main.py:1327-1328, :1398) —
    # same category as the already-stripped custom_llm_provider/deployment_id.
    "azure",
    "text_completion",
    "atext_completion",
    # Third-review blocker A: caller-injectable litellm logging/observability
    # control-plane. litellm 1.87.0 escalates raw curl/prompt/response logging to
    # WARNING on a truthy `litellm_request_debug` (litellm_logging.py:1143-1168);
    # `verbose`/`logger_fn`/`litellm_logging_obj` are the sibling logging hooks
    # read from kwargs (main.py:1264-1267). None is an OpenRouter generation
    # parameter. Owner-ratified pin extension (2026-07-20).
    "litellm_request_debug",
    "verbose",
    "logger_fn",
    "litellm_logging_obj",
    # Follow-up: request-selected callbacks mutate process-global LiteLLM state,
    # and their dynamic credentials/hosts can receive prompt/response data.
    "callbacks",
    "success_callback",
    "failure_callback",
    "litellm_params",
    "litellm_metadata",
    "turn_off_message_logging",
    "langfuse_public_key",
    "langfuse_secret",
    "langfuse_secret_key",
    "langfuse_host",
    "langfuse_prompt_version",
    "langsmith_api_key",
    "langsmith_project",
    "langsmith_base_url",
    "langsmith_sampling_rate",
    "langsmith_tenant_id",
    "humanloop_api_key",
    "arize_api_key",
    "arize_space_key",
    "arize_space_id",
    "posthog_api_key",
    "posthog_host",
    "braintrust_api_key",
    "braintrust_project",
    "braintrust_host",
    "slack_webhook_url",
    "lunary_public_key",
    # OME-735: litellm 1.95 added the Datadog dynamic-callback params. Mirrors the same
    # four names added to _CALLBACK_DYNAMIC_FIELDS in request_hardening.py. This pin is a
    # deliberate review checkpoint — the control plane only grows through it.
    "dd_api_key",
    "dd_agent_host",
    "dd_agent_port",
    "dd_site",
    # OME-1177: litellm 1.100 added `langfuse_environment` plus a New Relic
    # dynamic-callback trio. Mirrors the same three names added to
    # _CALLBACK_DYNAMIC_FIELDS in request_hardening.py. Same deliberate review
    # checkpoint as the dd_* block above.
    "langfuse_environment",
    "newrelic_api_key",
    "newrelic_region",
    "litellm_trusted_callback_vars",
    "user_api_key_auth_metadata",
}


def test_strip_list_is_exactly_the_d6_control_plane() -> None:
    assert DISPATCH_CONTROL_FIELDS == frozenset(_D6_CONTROL_FIELDS)


def test_mode_flip_flags_are_stripped_before_dispatch() -> None:
    """SEC-1: `azure: true` flips litellm onto its azure branch and
    `text_completion`/`atext_completion` flip the completion mode — a caller
    must not be able to bend dispatch any more than via the stripped
    `custom_llm_provider`/`deployment_id`."""
    body: dict[str, object] = {
        "model": "openrouter/a/b",
        "messages": [],
        "azure": True,
        "text_completion": True,
        "atext_completion": True,
    }
    assert set(strip_dispatch_controls(body)) == {"model", "messages"}


def test_strip_removes_every_control_field() -> None:
    body: dict[str, object] = {field: "attacker" for field in _D6_CONTROL_FIELDS}
    body["model"] = "anthropic/claude-sonnet-4-5"
    body["messages"] = [{"role": "user", "content": "hi"}]
    stripped = strip_dispatch_controls(body)
    assert set(stripped) == {"model", "messages"}


def test_strip_removes_caller_extra_headers() -> None:
    # INVARIANT: raw headers are control-plane input. Provider and credential
    # headers are created later by trusted gateway code, never accepted here.
    body = {
        "model": "anthropic/claude-sonnet-4-5",
        "messages": [],
        "extra_headers": {"authorization": "Bearer sk-ant-oat01-attacker"},
    }

    assert strip_dispatch_controls(body) == {
        "model": "anthropic/claude-sonnet-4-5",
        "messages": [],
    }


def test_strip_removes_nested_callback_metadata_without_mutating_input() -> None:
    body = {
        "model": "openrouter/a/b",
        "messages": [],
        "metadata": {
            "trace_id": "safe-provider-metadata",
            "langfuse_host": "https://attacker.invalid",
            "posthog_api_key": "attacker-key",
            "turn_off_message_logging": False,
            "headers": {
                "litellm-disable-message-redaction": True,
                "x-trace": "safe-header-metadata",
            },
        },
    }

    stripped = strip_dispatch_controls(body)

    assert stripped["metadata"] == {
        "trace_id": "safe-provider-metadata",
        "headers": {"x-trace": "safe-header-metadata"},
    }
    assert body["metadata"] == {
        "trace_id": "safe-provider-metadata",
        "langfuse_host": "https://attacker.invalid",
        "posthog_api_key": "attacker-key",
        "turn_off_message_logging": False,
        "headers": {
            "litellm-disable-message-redaction": True,
            "x-trace": "safe-header-metadata",
        },
    }


def test_strip_removes_litellm_metadata_alias_entirely() -> None:
    body = {
        "model": "openrouter/a/b",
        "messages": [],
        "litellm_metadata": {
            "headers": {"litellm-disable-message-redaction": True},
            "langfuse_host": "https://attacker.invalid",
        },
    }
    assert set(strip_dispatch_controls(body)) == {"model", "messages"}


def test_strip_removes_litellm_1_100_dynamic_callback_fields() -> None:
    # OME-1177: litellm 1.100 added `langfuse_environment` (a further Langfuse
    # dynamic param) and a New Relic dynamic-callback trio for per-team trace
    # routing. `newrelic_api_key` is a caller-injectable credential and
    # `langfuse_environment`/`newrelic_region` redirect where prompt/response
    # telemetry ships — same exfiltration category as the dd_* fields above.
    body = {
        "model": "openrouter/a/b",
        "messages": [],
        "langfuse_environment": "attacker-env",
        "newrelic_api_key": "attacker-key",
        "newrelic_region": "attacker-region",
        "metadata": {
            "trace_id": "safe-provider-metadata",
            "langfuse_environment": "attacker-env",
            "newrelic_api_key": "attacker-key",
            "newrelic_region": "attacker-region",
        },
    }

    stripped = strip_dispatch_controls(body)

    assert set(stripped) == {"model", "messages", "metadata"}
    assert stripped["metadata"] == {"trace_id": "safe-provider-metadata"}


def test_litellm_dynamic_callback_parameter_set_is_covered() -> None:
    supported = set(getattr(initialize_dynamic_callback_params, "_supported_callback_params"))
    assert supported <= DISPATCH_CONTROL_FIELDS


def test_strip_preserves_ordinary_and_provider_fields() -> None:
    body = {
        "model": "openrouter/anthropic/claude-fable-5",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.5,
        "max_tokens": 128,
        "timeout": 30,  # deliberately NOT stripped: gemini/codex/antigravity consume it
        "provider": {"order": ["anthropic"]},
        "plugins": [{"id": "web"}],
        "route": "fallback",
        "models": ["anthropic/claude-opus-4.8"],
        "tools": [{"type": "function"}],
        "stream": False,
    }
    assert strip_dispatch_controls(body) == body


def test_strip_returns_a_new_dict_without_mutating_the_input() -> None:
    body = {"model": "a/b", "messages": [], "fallbacks": ["x"]}
    stripped = strip_dispatch_controls(body)
    assert stripped is not body
    assert body["fallbacks"] == ["x"]
    assert "fallbacks" not in stripped


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (None, "model and messages are required"),
        ([1, 2], "model and messages are required"),
        ("text", "model and messages are required"),
        ({}, "model and messages are required"),
        ({"model": "a/b"}, "model and messages are required"),
        ({"messages": []}, "model and messages are required"),
        ({"model": 42, "messages": []}, "model must be a string"),
        ({"model": "a/b", "messages": "hi"}, "messages must be a list"),
        ({"model": "a/b", "messages": [{"role": "user"}, 42]}, "each message must be an object"),
        ({"model": "a/b", "messages": [], "stream": "yes"}, "stream must be a boolean"),
        ({"model": "a/b", "messages": [], "stream": 1}, "stream must be a boolean"),
        ({"model": "a/b", "messages": []}, None),
        ({"model": "a/b", "messages": [{"role": "user", "content": "hi"}]}, None),
        ({"model": "a/b", "messages": [], "stream": True}, None),
        ({"model": "a/b", "messages": [], "stream": False}, None),
    ],
)
def test_chat_body_shape_error(body: object, error: str | None) -> None:
    assert chat_body_shape_error(body) == error


# --- HTTP surface: untrusted input can never 500, controls never dispatch ---


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _seed_authenticated_profile(credential_blobs, account_id: str) -> None:
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, "default")),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )


async def _seed_anthropic_profile(credential_blobs, account_id: str) -> None:
    _seed_authenticated_profile(credential_blobs, account_id)
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )


def test_chat_malformed_json_returns_400_not_500(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=b'{"model": "anthropic/claude",',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "request body must be valid JSON"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"model": 42, "messages": []}, "model must be a string"),
        ({"model": "anthropic/claude", "messages": {"role": "user"}}, "messages must be a list"),
        ({"model": "anthropic/claude", "messages": [17]}, "each message must be an object"),
        (
            {"model": "anthropic/claude", "messages": [], "stream": "yes"},
            "stream must be a boolean",
        ),
    ],
)
def test_chat_shape_violations_return_400(authenticated_client, body: dict, error: str) -> None:
    resp = authenticated_client.post("/v1/chat/completions", json=body)
    assert resp.status_code == 400
    assert resp.json()["detail"] == error


@pytest.mark.asyncio
async def test_chat_strips_litellm_controls_for_every_provider(
    credential_blobs, authenticated_client
) -> None:
    """Caller-supplied LiteLLM control-plane fields never reach a provider
    dispatch (anthropic here), while the gateway's own injected credential
    replaces the caller's api_key."""
    account_id = _account_id(authenticated_client)
    await _seed_anthropic_profile(credential_blobs, account_id)

    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    with patch(
        "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion",
        fake_chat_completion,
    ):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4-5",
                "messages": [{"role": "user", "content": "hi"}],
                "api_key": "sk-evil-caller",
                "api_base": "https://evil.example",
                "base_url": "https://evil.example",
                "model_list": [{"model_name": "x"}],
                "fallbacks": [{"model": "y", "api_base": "https://evil.example"}],
                "num_retries": 99,
                "mock_response": "pwned",
                "custom_llm_provider": "evil",
                "input_cost_per_token": 0,
            },
        )

    assert resp.status_code == 200, resp.text
    for field in (
        "api_base",
        "base_url",
        "model_list",
        "fallbacks",
        "num_retries",
        "mock_response",
        "custom_llm_provider",
        "input_cost_per_token",
    ):
        assert field not in captured
    # The caller's key was stripped at ingress; the injected credential won.
    assert captured["api_key"] != "sk-evil-caller"
