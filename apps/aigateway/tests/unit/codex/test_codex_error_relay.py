"""OME-1136 decision 3: the Codex and Gemini plugins relay `CustomLLMError.message` only
through the shared provider-error screen.

INVARIANT: no credential, URL, email, path, request echo or bidi character from a provider
error reaches the client; the call's own credential withholds the whole text; a benign
gateway-authored message passes unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError

from aigateway.plugins.codex_provider import plugin as codex_module
from aigateway.plugins.gemini_provider import plugin as gemini_module

_HEX = "ab12" * 16
_PROMPT = "please summarise my private medical history " * 7
_POISON = (
    f"Codex upstream request failed with status 400: Bearer sk-proj-{_HEX} "
    "see https://internal.example/x?token=abc-secret-value mail ops@openai.com "
    f"org org-AbCdEf123456 path /var/run/secrets/kube echo '{_PROMPT}' ‮bidi"
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
_FALLBACK = "The upstream provider returned an error."

_PLUGINS = [
    pytest.param(codex_module, "get_litellm_codex_handler", "PLUGIN", id="codex"),
    pytest.param(gemini_module, "get_litellm_gemini_handler", "PLUGIN", id="gemini"),
]


def _raising(monkeypatch: pytest.MonkeyPatch, module: Any, getter: str, status: int, message: str):
    async def acompletion(**_kwargs):
        raise CustomLLMError(status_code=status, message=message)

    monkeypatch.setattr(module, getter, lambda: SimpleNamespace(acompletion=acompletion))


async def _detail(module: Any, attr: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    plugin = getattr(module, attr)
    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(
            body or {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        )
    detail = caught.value.detail
    assert isinstance(detail, dict)
    return detail


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "getter", "attr"), _PLUGINS)
async def test_poisoned_message_is_sanitized(monkeypatch, module, getter, attr) -> None:
    _raising(monkeypatch, module, getter, 400, _POISON)

    detail = await _detail(module, attr)

    for secret in _SECRETS:
        assert secret not in detail["message"]
    assert detail["message"].startswith(
        "Codex upstream request failed with status 400: [redacted] see [url] mail [email]"
    )
    assert len(detail["message"]) <= 140


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "getter", "attr"), _PLUGINS)
async def test_withheld_message_falls_back_to_the_generic_sentence(
    monkeypatch, module, getter, attr
) -> None:
    _raising(monkeypatch, module, getter, 400, "Traceback (most recent call last): api_key=abc")

    assert (await _detail(module, attr))["message"] == _FALLBACK


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "getter", "attr"), _PLUGINS)
async def test_the_calls_own_credential_withholds_the_message(
    monkeypatch, module, getter, attr
) -> None:
    _raising(monkeypatch, module, getter, 400, f"rejected x{_CREDENTIAL} here")
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "extra_headers": {"Authorization": f"Bearer {_CREDENTIAL}"},
    }

    detail = await _detail(module, attr, body)

    assert _CREDENTIAL not in detail["message"]
    assert detail["message"] == _FALLBACK


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "getter", "attr"), _PLUGINS)
async def test_benign_message_is_unchanged(monkeypatch, module, getter, attr) -> None:
    _raising(monkeypatch, module, getter, 401, "Codex upstream rejected OAuth token")

    assert (await _detail(module, attr))["message"] == "Codex upstream rejected OAuth token"
