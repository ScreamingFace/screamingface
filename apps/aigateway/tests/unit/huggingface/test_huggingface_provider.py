"""Hugging Face provider plugin unit behavior (SF-345).

Covers the contract a new api-key-only provider must satisfy: model registration
in router-suffix form, the API-key credential strategy (Bearer header + stable
credential slot), the no-OAuth shape, 401-only credential invalidation, and the
``prepare_chat_body`` guarantees (caller-auth stripping + gateway-owned api_base).
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.plugins.huggingface_provider.plugin import (
    PLUGIN,
    HuggingFaceProviderPlugin,
)

_ROUTER = "https://router.huggingface.co/v1"


class _FakeStore:
    """Dict-backed CredentialBlobStore (Protocol) stand-in — no DB."""

    def __init__(self, api_key: str) -> None:
        self._blob = json.dumps({"auth_type": "api_key", "api_key": api_key})

    async def read(self, service: str, account: str) -> str | None:
        return self._blob

    async def write(self, service: str, account: str, value: str) -> None: ...

    async def delete(self, service: str, account: str) -> None: ...

    async def mutate(self, service: str, account: str, mutator) -> None:
        self._blob = mutator(self._blob)


def test_plugin_identity() -> None:
    assert isinstance(PLUGIN, HuggingFaceProviderPlugin)
    assert PLUGIN.custom_llm_provider == "huggingface"
    # credential namespace defaults to the provider id (name already matches)
    assert PLUGIN.credential_service_provider() == "huggingface"


def test_register_models_are_router_entries() -> None:
    entries = PLUGIN.register_models()
    assert entries, "must contribute at least one model"
    for entry in entries:
        assert entry.model_name.startswith("huggingface/")
        # model_name and the litellm dispatch string are identical (:suffix slug)
        assert entry.litellm_params["model"] == entry.model_name
        # api_base pinned to the unified router -> keeps litellm request-local
        assert entry.litellm_params["api_base"] == _ROUTER


def test_supports_api_key() -> None:
    assert PLUGIN.supports_api_key() is True


def test_no_oauth_surface() -> None:
    # Novel shape: api-key-only with NO OAuth. Core routes api_key without oauth_config.
    assert PLUGIN.oauth_config() is None
    assert PLUGIN.oauth_strategy_for("acct:conn") is None


def test_streaming_enabled_by_default() -> None:
    # Decision (SF-345): keep streaming on via the built-in litellm router path.
    assert PLUGIN.supports_chat_streaming() is True


@pytest.mark.parametrize(
    ("status", "marks"),
    [(401, True), (403, False), (429, False), (500, False), (200, False)],
)
def test_marks_credential_error_on_401_only(status: int, marks: bool) -> None:
    # 401 => bad/missing token (invalidate). 403 is ambiguous (model access vs token),
    # so it must NOT nuke the stored credential.
    assert PLUGIN.should_mark_credential_error_on_dispatch_status(status) is marks


def test_api_key_strategy_shape() -> None:
    strategy = PLUGIN.api_key_strategy_for("acct:conn", credential_store=_FakeStore("hf_x"))
    assert isinstance(strategy, ApiKeyStrategy)
    assert strategy.credential_service() == "aigateway:huggingface:acct:conn"
    assert strategy.credential_account() == "default"


@pytest.mark.asyncio
async def test_api_key_strategy_builds_bearer_header() -> None:
    strategy = PLUGIN.api_key_strategy_for(
        "acct:conn", credential_store=_FakeStore("hf_secrettoken")
    )
    headers = await strategy.get_authorization_header()
    assert headers == {"Authorization": "Bearer hf_secrettoken"}


def test_prepare_chat_body_injects_router_api_base() -> None:
    out = PLUGIN.prepare_chat_body(
        {"model": "huggingface/deepseek-ai/DeepSeek-R1:novita", "messages": []}
    )
    assert out["api_base"] == _ROUTER
    # model keeps the 'huggingface/' prefix (litellm needs it to resolve the provider)
    assert out["model"] == "huggingface/deepseek-ai/DeepSeek-R1:novita"


def test_prepare_chat_body_overrides_caller_api_base() -> None:
    out = PLUGIN.prepare_chat_body(
        {"model": "huggingface/x/y:novita", "messages": [], "api_base": "http://evil.example"}
    )
    assert out["api_base"] == _ROUTER


def test_prepare_chat_body_strips_caller_credentials() -> None:
    out = PLUGIN.prepare_chat_body(
        {
            "model": "huggingface/x/y:novita",
            "messages": [],
            "api_key": "caller-key",
            "extra_headers": {
                "Authorization": "Bearer attacker",
                "X-Api-Key": "attacker",
                "proxy-authorization": "attacker",
                "X-Trace": "keep-me",
            },
        }
    )
    assert "api_key" not in out
    # only the non-auth header survives (case-insensitive strip of auth names)
    assert out["extra_headers"] == {"X-Trace": "keep-me"}


def test_prepare_chat_body_drops_all_auth_headers_leaves_none() -> None:
    out = PLUGIN.prepare_chat_body(
        {
            "model": "huggingface/x/y:novita",
            "messages": [],
            "extra_headers": {"authorization": "Bearer x"},
        }
    )
    assert "extra_headers" not in out


def test_prepare_chat_body_drops_non_dict_extra_headers() -> None:
    out = PLUGIN.prepare_chat_body(
        {"model": "huggingface/x/y:novita", "messages": [], "extra_headers": "bogus"}
    )
    assert "extra_headers" not in out
