"""Phase 4 (OME-479): OpenRouter fail-closed dispatch + P0 provider_params.top_k.

Runs the REAL route + OpenRouterProviderPlugin, capturing the kwargs handed to
``litellm.acompletion`` (the last gateway-controlled point). Proves:

- the P0 promotion ``provider_params.top_k`` projects to ``extra_body.top_k``
  and reaches dispatch, and the INSTALLED litellm openrouter transform carries
  ``extra_body.top_k`` onto the wire body (final-transform proof, plan §6.1/§12);
- unknown / unruled-nested / malformed optional params reject with HTTP 400
  BEFORE any dispatch (fail closed);
- the seeded rule set is the single source behind the model summary.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aigateway.core.chat_parameters import inline_supported_parameters
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_KEY = "sk-or-v1-test"
_MODEL = "openrouter/anthropic/claude-fable-5"


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit test double (per tests/unit/conftest.py AIDEV-NOTE): this module
    # is outside the frozen legacy allowlist, so it opts in to a VALID readiness
    # result — key validation is not what these projection tests exercise.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self, _plugin, _provider, _api_key) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture()
def enabled_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _create_connection(client) -> None:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": _KEY},
    )
    assert resp.status_code == 201, resp.text


def _fake_acompletion(captured: dict):
    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {"id": "or-1", "choices": [{"message": {"content": "ok"}}]}
        )

    return fake_acompletion


def _post_chat(client, body: dict):
    payload = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}], **body}
    return client.post("/v1/chat/completions", json=payload)


def test_provider_params_top_k_projects_into_extra_body(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"provider_params": {"top_k": 40}})
    assert resp.status_code == 200, resp.text
    # projected to the provider-native channel; wrapper fully consumed.
    assert captured["extra_body"] == {"top_k": 40}
    assert "provider_params" not in captured
    assert "top_k" not in captured  # only under extra_body


def test_unknown_parameter_rejects_before_dispatch(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"banana": 1})
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_parameters"
    assert detail["rejected"] == {"banana": "unknown"}
    assert captured == {}  # fail closed: no provider call happened


def test_unruled_provider_params_key_rejects(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"provider_params": {"mystery": 1}})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {"provider_params.mystery": "unknown"}
    assert captured == {}


def test_malformed_top_k_rejects(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"provider_params": {"top_k": "high"}})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {"provider_params.top_k": "malformed"}
    assert captured == {}


def test_extra_body_top_k_survives_installed_litellm_openrouter_transform() -> None:
    # FINAL-TRANSFORM PROOF (plan §6.1): the P0 promotion is enabled only
    # because the INSTALLED litellm openrouter transform carries a caller
    # extra_body key onto the wire body. If litellm changes this, the P0 rule
    # must be re-reviewed — this test is the tripwire.
    from litellm.llms.openrouter.chat.transformation import OpenrouterConfig
    from litellm.utils import get_optional_params

    upstream = "google/gemini-2.0-flash-001"
    optional = get_optional_params(
        model=upstream, custom_llm_provider="openrouter", extra_body={"top_k": 40}
    )
    assert optional.get("extra_body") == {"top_k": 40}
    wire = OpenrouterConfig().transform_request(
        model=upstream,
        messages=[{"role": "user", "content": "hi"}],
        optional_params=dict(optional),
        litellm_params={},
        headers={},
    )
    assert wire.get("top_k") == 40


def test_control_field_stripped_before_classify_allows_valid_param(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # COMPOSITION (TRIZ Prior Action): a caller-sent litellm orchestration field
    # (`caching`) is neutralized by the provider's pre-classify control strip, so
    # the classifier never sees it and a co-sent VALID param (`temperature`) still
    # projects and dispatches. Proves the control strip runs BEFORE fail-closed
    # classification — not a 400 for the whole request.
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"caching": True, "temperature": 0.5})
    assert resp.status_code == 200, resp.text
    assert captured["temperature"] == 0.5  # valid param survived classification
    assert captured["caching"] is False  # gateway forces it; caller value never wins
    assert "guardrails" not in captured


def test_seeded_rules_are_the_single_source_of_the_summary() -> None:
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True))
    rules = plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key")
    summary = set(inline_supported_parameters(rules, available_auth_modes=("api_key",)))
    assert {"temperature", "max_tokens", "provider_params.top_k"} <= summary
    # OME-646: the schema-less native routing controls are no longer ruled, so the
    # summary must not advertise them either — /v1/models and dispatch agree.
    assert summary.isdisjoint({"provider", "plugins", "route", "models"})


# --- OME-596 (§9): OpenRouter provider_params.top_k accepts the documented 0 (disable) ---


def test_top_k_zero_is_accepted_and_reaches_dispatch(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # STORY: as an OpenRouter caller I disable top-k sampling by sending top_k=0 (the
    # provider-documented "0 or above", 0 == disabled). INVARIANT: 0 is falsy but must NOT
    # be dropped — it projects to extra_body.top_k and reaches dispatch verbatim, exactly
    # like a non-zero value (contrast: a truthiness filter would silently swallow it).
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"provider_params": {"top_k": 0}})
    assert resp.status_code == 200, resp.text
    assert captured["extra_body"] == {"top_k": 0}
    assert "provider_params" not in captured
    assert "top_k" not in captured  # only under extra_body


def test_negative_top_k_rejects_fail_closed(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # WHY: widening the lower bound to 0 must NOT widen it below 0 — a negative top_k is
    # not a documented OpenRouter value, so it still fails closed at classification before
    # any credential access (the OpenRouter schema is minimum=0, not unbounded-below).
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"provider_params": {"top_k": -1}})
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["rejected"] == {"provider_params.top_k": "malformed"}
    assert captured == {}  # fail closed: no provider call happened


def test_top_k_zero_survives_installed_litellm_openrouter_transform() -> None:
    # FINAL-TRANSFORM PROOF (plan §6.1/§9) at the newly-enabled boundary: top_k=0 is
    # accepted only because the INSTALLED litellm openrouter transform carries the falsy 0
    # onto the wire body unchanged. If litellm ever starts dropping falsy extra_body values,
    # this tripwire fails and the minimum=0 rule must be re-reviewed.
    from litellm.llms.openrouter.chat.transformation import OpenrouterConfig
    from litellm.utils import get_optional_params

    upstream = "google/gemini-2.0-flash-001"
    optional = get_optional_params(
        model=upstream, custom_llm_provider="openrouter", extra_body={"top_k": 0}
    )
    assert optional.get("extra_body") == {"top_k": 0}
    wire = OpenrouterConfig().transform_request(
        model=upstream,
        messages=[{"role": "user", "content": "hi"}],
        optional_params=dict(optional),
        litellm_params={},
        headers={},
    )
    assert wire.get("top_k") == 0


# --- OME-993 (§9): validated reasoning_effort for the OpenRouter provider ------------


def test_reasoning_effort_is_accepted_and_reaches_dispatch(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # STORY: the DRACO judge is a reasoning model — without a validated low-effort
    # throttle it can burn its whole token budget thinking (GH #740). The standard
    # field projects direct and reaches dispatch verbatim.
    _create_connection(authenticated_client)
    captured: dict = {}
    with patch("litellm.acompletion", _fake_acompletion(captured)):
        resp = _post_chat(authenticated_client, {"reasoning_effort": "low"})
    assert resp.status_code == 200, resp.text
    assert captured["reasoning_effort"] == "low"


def test_reasoning_effort_outside_the_proven_ladder_rejects_fail_closed(
    enabled_openrouter, credential_blobs, authenticated_client
) -> None:
    # WHY a provider-local schema: only low/medium/high are proven through the
    # installed transform for OpenRouter — "none"/"minimal" are other providers'
    # spellings and fail closed here rather than dispatching an unproven value.
    _create_connection(authenticated_client)
    for value in ("none", "minimal", "banana", 3):
        captured: dict = {}
        with patch("litellm.acompletion", _fake_acompletion(captured)):
            resp = _post_chat(authenticated_client, {"reasoning_effort": value})
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]["rejected"] == {"reasoning_effort": "malformed"}
        assert captured == {}  # fail closed: no provider call happened


def test_reasoning_effort_survives_installed_litellm_openrouter_transform() -> None:
    # FINAL-TRANSFORM PROOF (plan §6.1/§12): the rule is enabled only because the
    # INSTALLED litellm openrouter transform carries reasoning_effort onto the wire
    # body top-level for reasoning-capable models (OpenRouter's OpenAI-compat field).
    # If litellm changes this, the rule must be re-reviewed — this is the tripwire.
    from litellm.llms.openrouter.chat.transformation import OpenrouterConfig
    from litellm.utils import get_optional_params

    upstream = "google/gemini-3.1-pro-preview"  # DRACO's pinned judge
    optional = get_optional_params(
        model=upstream, custom_llm_provider="openrouter", reasoning_effort="low"
    )
    assert optional.get("reasoning_effort") == "low"
    wire = OpenrouterConfig().transform_request(
        model=upstream,
        messages=[{"role": "user", "content": "hi"}],
        optional_params=dict(optional),
        litellm_params={},
        headers={},
    )
    assert wire.get("reasoning_effort") == "low"


def test_reasoning_effort_is_advertised_in_the_summary() -> None:
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True))
    rules = plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key")
    summary = set(inline_supported_parameters(rules, available_auth_modes=("api_key",)))
    assert "reasoning_effort" in summary
