"""The provider plugins' credential errors name a credential, never a retired Profile.

FEATURE: OME-1138 follow-up — retire the leftover Profile wording
(`docs/spec/2026-11-16-ome-1138-leftover-profile-wording.md` §2.1).

STORY: as a caller whose provider credential is missing or was revoked, the error tells me to
reconnect the provider, in the gateway's own vocabulary, instead of naming a Profile and the
retired desktop app.

INVARIANT: no credential error of the four OAuth plugins, and not the Gemini 401, contains
"profile" or "Electron".
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from litellm.llms.custom_llm import CustomLLMError
from litellm.types.utils import ModelResponse

from aigateway.core.errors import CredentialNotFoundError, ReauthRequiredError
from aigateway.plugins.anthropic_provider.auth import AnthropicOAuth
from aigateway.plugins.antigravity_provider.auth import AntigravityOAuth
from aigateway.plugins.codex_provider.auth import CodexOAuth
from aigateway.plugins.gemini_provider.auth import GeminiOAuth
from aigateway.plugins.gemini_provider.chat_handler import GeminiCustomLLM


class _Store:
    def __init__(self, payload: str | None) -> None:
        self.payload = payload

    async def read(self, service: str, account: str) -> str | None:
        return self.payload

    async def write(self, service: str, account: str, value: str) -> None:
        self.payload = value

    async def delete(self, service: str, account: str) -> None:
        self.payload = None


def _rejecting_client() -> httpx.AsyncClient:
    # WHY 400 invalid_grant: `is_reauth_refresh_failure` reads it as a dead refresh token, so the
    # plugin raises ReauthRequiredError, the error whose text this module pins.
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(400, json={"error": "invalid_grant"})
    )
    return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _expired_tokens() -> str:
    # WHY one blob for all four plugins: each reads only its own keys, and Codex refuses a
    # stored blob without `id_token` before it tries a refresh.
    return json.dumps(
        {
            "access_token": "tok-expired",
            "refresh_token": "rt-1",
            "id_token": "id-1",
            "expires_at_ms": int((time.time() - 60) * 1000),
            "token_type": "Bearer",
            "account_id": "acct-1",
        }
    )


def _anthropic(store: _Store) -> Any:
    return AnthropicOAuth(
        credential_name="default", credential_store=store, http_client_factory=_rejecting_client
    )


def _antigravity(store: _Store) -> Any:
    return AntigravityOAuth(
        credential_name="default",
        client_secret="test-secret",
        credential_store=store,
        http_client_factory=_rejecting_client,
    )


def _codex(store: _Store) -> Any:
    return CodexOAuth(
        credential_name="default", credential_store=store, http_client_factory=_rejecting_client
    )


def _gemini(store: _Store) -> Any:
    return GeminiOAuth(
        credential_name="default", credential_store=store, http_client_factory=_rejecting_client
    )


_PLUGINS: list[tuple[str, Callable[[_Store], Any]]] = [
    ("anthropic", _anthropic),
    ("antigravity", _antigravity),
    ("codex", _codex),
    ("gemini", _gemini),
]


def _assert_no_retired_wording(message: str) -> None:
    assert "profile" not in message.lower()
    assert "electron" not in message.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "build"), _PLUGINS)
async def test_missing_tokens_name_the_credential(
    provider: str, build: Callable[[_Store], Any]
) -> None:
    strategy = build(_Store(payload=None))

    with pytest.raises(CredentialNotFoundError) as caught:
        await strategy.get_authorization_header()

    message = str(caught.value)
    assert message == f"No tokens for {provider} credential 'default'. Reconnect the provider."
    _assert_no_retired_wording(message)


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "build"), _PLUGINS)
async def test_rejected_refresh_names_the_credential(
    provider: str, build: Callable[[_Store], Any]
) -> None:
    strategy = build(_Store(payload=_expired_tokens()))

    with pytest.raises(ReauthRequiredError) as caught:
        await strategy.get_authorization_header()

    message = str(caught.value)
    assert message == (
        "Refresh token rejected for credential 'default' (HTTP 400). Re-auth required."
    )
    _assert_no_retired_wording(message)


@pytest.mark.asyncio
async def test_gemini_without_any_credential_names_what_it_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(CustomLLMError) as caught:
        await GeminiCustomLLM().acompletion(
            model="gemini-cli/gemini-2.5-flash",
            messages=[{"role": "user", "content": "ping"}],
            api_base="",
            custom_prompt_dict={},
            model_response=ModelResponse(),
            print_verbose=lambda *_args, **_kwargs: None,
            encoding=None,
            api_key=None,
            logging_obj=None,
            optional_params={},
        )

    assert caught.value.status_code == 401
    assert caught.value.message == (
        "Gemini requires a connected OAuth or API-key credential, or GEMINI_API_KEY/GOOGLE_API_KEY"
    )
    _assert_no_retired_wording(caught.value.message)
