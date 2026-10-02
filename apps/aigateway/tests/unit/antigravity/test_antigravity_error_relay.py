"""OME-1136 (owner decision 2026-10-02): the Antigravity plugin relays `CustomLLMError.message`
only through the shared provider-error screen, like Codex and Gemini.

INVARIANT: a provider-authored message (e.g. an SSE stream error) is screened — no credential,
URL, email, path, request echo or bidi character reaches the client; the call's own credential
withholds the whole text. The gateway-authored activation message passes unchanged (it is
longer than the 140-character relay cap, and it is not provider text).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError

from aigateway.plugins.antigravity_provider import plugin as antigravity_module
from aigateway.plugins.antigravity_provider.chat_handler import (
    ANTIGRAVITY_ACTIVATION_REQUIRED_CODE,
    ANTIGRAVITY_ACTIVATION_REQUIRED_MESSAGE,
)

_HEX = "ab12" * 16
_PROMPT = "please summarise my private medical history " * 7
_POISON = (
    f"Stream failed: Bearer sk-proj-{_HEX} see https://internal.example/x?token=abc-secret-value "
    "mail ops@openai.com org org-AbCdEf123456 path /var/run/secrets/kube "
    f"echo '{_PROMPT}' ‮bidi"
)
_SECRETS = (
    f"sk-proj-{_HEX}",
    "abc-secret-value",
    "internal.example",
    "ops@openai.com",
    "org-AbCdEf123456",
    "/var/run/secrets",
    "private medical history",
    "‮",
)
_CREDENTIAL = "oauth-access-token-value-123"


def _raising(monkeypatch: pytest.MonkeyPatch, error: CustomLLMError) -> None:
    async def acompletion(**_kwargs):
        raise error

    monkeypatch.setattr(
        antigravity_module,
        "get_litellm_antigravity_handler",
        lambda: SimpleNamespace(acompletion=acompletion),
    )


async def _detail(body: dict[str, Any] | None = None) -> dict[str, Any]:
    with pytest.raises(HTTPException) as caught:
        await antigravity_module.PLUGIN.chat_completion(
            body or {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        )
    detail = caught.value.detail
    assert isinstance(detail, dict)
    return detail


@pytest.mark.asyncio
async def test_poisoned_stream_error_is_sanitized(monkeypatch) -> None:
    _raising(monkeypatch, CustomLLMError(status_code=502, message=_POISON))

    detail = await _detail()

    for secret in _SECRETS:
        assert secret not in detail["message"]
    assert detail["message"].startswith("Stream failed: [redacted] see [url] mail [email]")
    assert len(detail["message"]) <= 140


@pytest.mark.asyncio
async def test_withheld_message_falls_back_to_the_generic_sentence(monkeypatch) -> None:
    _raising(monkeypatch, CustomLLMError(status_code=502, message="token: abc /home/me/key"))

    assert (await _detail())["message"] == "The upstream provider returned an error."


@pytest.mark.asyncio
async def test_the_calls_own_credential_withholds_the_message(monkeypatch) -> None:
    _raising(monkeypatch, CustomLLMError(status_code=502, message=f"bad x{_CREDENTIAL} here"))
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "extra_headers": {"Authorization": f"Bearer {_CREDENTIAL}"},
    }

    detail = await _detail(body)

    assert _CREDENTIAL not in detail["message"]
    assert detail["message"] == "The upstream provider returned an error."


@pytest.mark.asyncio
async def test_gateway_authored_activation_message_is_unchanged(monkeypatch) -> None:
    error = CustomLLMError(status_code=403, message=ANTIGRAVITY_ACTIVATION_REQUIRED_MESSAGE)
    error.detail_code = ANTIGRAVITY_ACTIVATION_REQUIRED_CODE  # type: ignore[attr-defined]
    _raising(monkeypatch, error)

    assert await _detail() == {
        "code": ANTIGRAVITY_ACTIVATION_REQUIRED_CODE,
        "message": ANTIGRAVITY_ACTIVATION_REQUIRED_MESSAGE,
    }
