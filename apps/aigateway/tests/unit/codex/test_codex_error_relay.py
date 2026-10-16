"""OME-1136 decision 3: the Codex and Gemini plugins relay `CustomLLMError.message` only
through the shared provider-error screen.

INVARIANT: no credential, URL, email, path, request echo or bidi character from a provider
error reaches the client; the call's own credential withholds the whole text; a benign
gateway-authored message passes unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError

from aigateway.plugins.codex_provider import chat_handler as codex_handler
from aigateway.plugins.codex_provider import plugin as codex_module
from aigateway.plugins.gemini_provider import chat_handler as gemini_handler
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
    # WHY 400, not 401 (#1233 review): a 401 never relays plugin text any more — see below.
    _raising(monkeypatch, module, getter, 400, "Codex upstream rejected the request")

    assert (await _detail(module, attr))["message"] == "Codex upstream rejected the request"


# --- #1233 review: status-aware boundary + bounded body extraction -----------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "getter", "attr"), _PLUGINS)
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "The stored provider credential was rejected."),
        (429, "The upstream provider is rate limiting requests."),
    ],
)
async def test_auth_and_rate_limit_never_relay_plugin_text(
    monkeypatch, module, getter, attr, status, expected
) -> None:
    _raising(monkeypatch, module, getter, status, "A perfectly benign explanation")

    assert (await _detail(module, attr))["message"] == expected


_HTML_PII = (
    b"<html><body><h1>502 Bad Gateway</h1><p>Patient: Jane Doe, SSN 123-45-6789</p>"
    b"<p>See internal.example/admin</p></body></html>"
)
_HTML_LEAKS = ("Jane Doe", "123-45-6789", "internal.example", "<html")
_JSON_ERROR = b'{"error": {"message": "Unsupported parameter: \'top_k\'", "trace": "Jane Doe"}}'


def _wire_response(status: int, content: bytes) -> httpx.Response:
    return httpx.Response(
        status, content=content, request=httpx.Request("POST", "https://upstream.test/v1")
    )


async def _codex_errors(status: int, content: bytes) -> list[CustomLLMError]:
    response = _wire_response(status, content)
    from_response = await codex_handler._status_error_from_response(response)
    assert from_response is not None
    from_exception = codex_handler._status_error_from_exception(
        httpx.HTTPStatusError("boom", request=response.request, response=response)
    )
    return [from_response, from_exception]


def _gemini_errors(status: int, content: bytes) -> list[CustomLLMError]:
    return [gemini_handler._error_from_response(_wire_response(status, content), "API")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "getter", "errors"),
    [
        pytest.param(codex_module, "get_litellm_codex_handler", _codex_errors, id="codex"),
        pytest.param(gemini_module, "get_litellm_gemini_handler", _gemini_errors, id="gemini"),
    ],
)
async def test_an_html_error_page_never_reaches_the_client(
    monkeypatch, module, getter, errors
) -> None:
    built = errors(502, _HTML_PII)
    for error in await built if hasattr(built, "__await__") else built:
        for leak in _HTML_LEAKS:
            assert leak not in error.message
        _raising(monkeypatch, module, getter, error.status_code, error.message)
        detail = await _detail(module, "PLUGIN")
        for leak in _HTML_LEAKS:
            assert leak not in detail["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "errors",
    [pytest.param(_codex_errors, id="codex"), pytest.param(_gemini_errors, id="gemini")],
)
async def test_a_json_error_body_relays_only_its_message_field(errors) -> None:
    built = errors(400, _JSON_ERROR)
    for error in await built if hasattr(built, "__await__") else built:
        assert error.message.endswith(": Unsupported parameter: 'top_k'")
        assert "Jane Doe" not in error.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "errors",
    [pytest.param(_codex_errors, id="codex"), pytest.param(_gemini_errors, id="gemini")],
)
async def test_a_raw_top_level_message_body_is_not_relayed(errors) -> None:
    # WHY (#1233 second review): valid JSON with an unapproved top-level `message` is an
    # unknown raw shape; it must fall back to the generic sentence like HTML does.
    built = errors(502, b'{"message": "Jane Doe SSN 123-45-6789 at 10.0.0.1/admin"}')
    for error in await built if hasattr(built, "__await__") else built:
        assert "Jane Doe" not in error.message
        assert "10.0.0.1" not in error.message
