"""BYOM responses must remain valid Unicode through the actual JSON response boundary.

# FEATURE: OME-1712 — readiness cannot publish a key on a completion that will fail UTF-8
# serialization in chat. Check every returned string, not just assistant content.
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.responses import JSONResponse

from aigateway.core.api_key_validation import ApiKeyValidationState
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.plugins.remote_endpoint.completion import decode_completion
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .conftest import Harness, chat, chat_body, put_key
from .fixtures import ACCOUNT_A, ENDPOINT_A, JSON_TYPE, two_endpoint_document

KEY = "sk-unicode-current-0001"
REPLACEMENT = "sk-unicode-replacement-0002"


def _completion(content: str = "ok", **metadata: Any) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        **metadata,
    }


INVALID_COMPLETIONS = {
    "content-high": _completion("\ud800"),
    "content-low": _completion("\udfff"),
    "metadata-key": _completion(metadata={"\ud800": "value"}),
    "metadata-value": _completion(metadata={"nested": "\udc00"}),
    "nested-list": _completion(metadata=[{"nested": ["\ud800"]}]),
    "nested-list-key": _completion(metadata=[{"\udfff": "value"}]),
}
VALID_TEXTS = ("", "\u96ea", "\U0001f600", "e\u0301", "\n\t\u0000", r"\ud800")


def _wire(body: dict[str, Any], *, ensure_ascii: bool = True) -> bytes:
    return json.dumps(body, ensure_ascii=ensure_ascii).encode("utf-8")


@pytest.mark.parametrize("name", INVALID_COMPLETIONS)
def test_decoder_refuses_surrogates_anywhere_in_the_returned_document(name: str) -> None:
    assert decode_completion(JSON_TYPE, _wire(INVALID_COMPLETIONS[name])) is None


@pytest.mark.parametrize("ensure_ascii", [True, False], ids=["escaped", "utf8"])
@pytest.mark.parametrize("text", VALID_TEXTS)
def test_valid_unicode_is_preserved_and_can_be_rendered(text: str, ensure_ascii: bool) -> None:
    expected = _completion(text, metadata={"\U0001f600": [text]})

    decoded = decode_completion(JSON_TYPE, _wire(expected, ensure_ascii=ensure_ascii))

    assert decoded == expected
    # INVARIANT: acceptance includes renderability at the actual response boundary. Encoding
    # a valid surrogate pair as two JSON escapes must not be mistaken for an isolated surrogate.
    assert json.loads(bytes(JSONResponse(decoded).body)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("name", INVALID_COMPLETIONS)
async def test_readiness_and_dispatch_refuse_invalid_unicode(name: str) -> None:
    body = _wire(INVALID_COMPLETIONS[name])
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=body, headers={"content-type": JSON_TYPE})

    definition = parse_remote_endpoint_config(two_endpoint_document()).endpoints[0]
    plugin = RemoteEndpointPlugin(definition, transport=httpx.MockTransport(respond))

    readiness = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)

    assert readiness is not None
    assert readiness.state is ApiKeyValidationState.UNAVAILABLE
    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion({**chat_body(ENDPOINT_A), "api_key": KEY})
    assert caught.value.status_code == 502
    detail: Any = caught.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "provider_error"
    assert len(sent) == 2


@pytest.mark.parametrize("name", INVALID_COMPLETIONS)
def test_invalid_unicode_replacement_preserves_the_working_key(
    byom: Harness, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    bad_body = _wire(INVALID_COMPLETIONS[name])
    sent: list[str] = []
    expected = _completion("old key still works")

    def respond(request: httpx.Request) -> httpx.Response:
        bearer = request.headers["authorization"]
        sent.append(bearer)
        body = bad_body if bearer == f"Bearer {REPLACEMENT}" else _wire(expected)
        return httpx.Response(200, content=body, headers={"content-type": JSON_TYPE})

    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        plugin = cast(FastAPI, client.app).state.providers.get(ENDPOINT_A)
        assert isinstance(plugin, RemoteEndpointPlugin)
        # Replace only the HTTP boundary: normal validation, publication and encrypted storage
        # still decide whether this key can replace the working one.
        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(plugin, "_transport", transport)
        monkeypatch.setattr(plugin.api_key_validator(), "_transport", transport)

        replacement = put_key(client, ACCOUNT_A, ENDPOINT_A, REPLACEMENT)
        assert replacement.status_code == 503
        assert replacement.json()["detail"]["code"] == "api_key_validation_unavailable"
        assert REPLACEMENT not in replacement.text
        response = chat(client, ACCOUNT_A, ENDPOINT_A)

    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) == KEY
    assert response.status_code == 200
    assert response.json()["choices"] == expected["choices"]
    assert sent == [f"Bearer {REPLACEMENT}", f"Bearer {KEY}"]
