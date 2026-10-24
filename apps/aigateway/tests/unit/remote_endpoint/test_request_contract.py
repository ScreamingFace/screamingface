"""What a request to a configured endpoint may carry, and the one request both branches send.

# FEATURE: hosted BYOM — the `openai-chat-basic-v1` request is text messages plus `max_tokens`;
# no tools, images or other content parts.
# INVARIANT: readiness sends exactly the request an ordinary chat sends, with no optional field,
# so a key is published only after the endpoint accepted the shape chat sends by default.
# INVARIANT: a request outside the text contract is refused before any key is read and before any
# upstream request; a plain text conversation is forwarded unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import ApiKeyValidationState
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.credential_blob.store import ORMStore
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .conftest import Harness, chat_body, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ALIAS,
    ENDPOINT_A,
    FINISHED_COMPLETION,
    UPSTREAM_MODEL,
    two_endpoint_document,
)

KEY = "sk-alice-on-a-request-0001"
PING = [{"role": "user", "content": "ping"}]
CONVERSATION = [
    {"role": "system", "content": "Answer briefly."},
    {"role": "user", "content": "ping"},
    {"role": "assistant", "content": "pong"},
    {"role": "user", "content": ""},
]
_IMAGE = {"type": "image_url", "image_url": {"url": "https://img.byom.test/x.png"}}
_MEDIA, _MESSAGE = "unsupported_content_part", "unsupported_message"
# `messages` values outside the text contract, each with the refusal code it must get.
OUTSIDE_THE_CONTRACT: dict[str, tuple[Any, str]] = {
    "image-part": ([{"role": "user", "content": [{"type": "text", "text": "hi"}, _IMAGE]}], _MEDIA),
    "audio-part": ([{"role": "user", "content": [{"type": "input_audio"}]}], _MEDIA),
    "text-part-list": ([{"role": "user", "content": [{"type": "text", "text": "hi"}]}], _MESSAGE),
    "tool-role": ([{"role": "tool", "content": "42", "tool_call_id": "c1"}], _MESSAGE),
    "assistant-tool-calls": (
        [*PING, {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]}],
        _MESSAGE,
    ),
    "unknown-role": ([{"role": "wizard", "content": "x"}], _MESSAGE),
    "extra-field": ([{"role": "user", "content": "x", "name": "alice"}], _MESSAGE),
    "number-content": ([{"role": "user", "content": 7}], _MESSAGE),
    "no-messages": ([], _MESSAGE),
}


def _chat(client: TestClient, body: dict[str, Any]) -> httpx.Response:
    return client.post("/v1/chat/completions", json=body, headers=tenant_headers(ACCOUNT_A))


def _key_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every read of endpoint A's stored keys from now on."""
    reads: list[str] = []
    original = ORMStore.read

    async def spy(self: ORMStore, service: str, account: str) -> str | None:
        if service.startswith(f"aigateway:{ENDPOINT_A}:"):
            reads.append(service)
        return await original(self, service, account)

    monkeypatch.setattr(ORMStore, "read", spy)
    return reads


@pytest.mark.asyncio
async def test_readiness_sends_the_request_dispatch_builds() -> None:
    sent: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=FINISHED_COMPLETION)

    definition = parse_remote_endpoint_config(two_endpoint_document()).endpoints[0]
    plugin = RemoteEndpointPlugin(definition, transport=httpx.MockTransport(respond))
    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)
    request = {"model": f"{ENDPOINT_A}/{ALIAS}", "messages": PING}
    await plugin.chat_completion({**plugin.prepare_chat_body(request), "api_key": KEY})

    assert result is not None and result.state is ApiKeyValidationState.VALID
    probe, dispatched = sent
    assert probe == dispatched == {"model": UPSTREAM_MODEL, "messages": PING}


def test_an_ordinary_chat_sends_exactly_what_the_attach_probe_sent(byom: Harness) -> None:
    # WHY through the routes: the probe must match what the chat route sends when the caller sets
    # no optional field, not a request built by hand for the comparison.
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        response = _chat(client, chat_body(ENDPOINT_A))

    assert response.status_code == 200, response.text
    assert [call.probe for call in byom.upstream.calls] == [True, False]
    probe, dispatched = byom.upstream.bodies
    assert probe == dispatched == {"model": UPSTREAM_MODEL, "messages": PING}


def test_dispatch_forwards_a_valid_max_tokens(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        response = _chat(client, {**chat_body(ENDPOINT_A), "max_tokens": 5})

    assert response.status_code == 200, response.text
    assert byom.upstream.bodies[-1] == {"model": UPSTREAM_MODEL, "messages": PING, "max_tokens": 5}


@pytest.mark.parametrize("value", [0, -1, "5", 1.5])
def test_an_invalid_max_tokens_is_refused_before_any_upstream_call(
    byom: Harness, value: Any
) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        byom.upstream.calls.clear()
        response = _chat(client, {**chat_body(ENDPOINT_A), "max_tokens": value})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "unsupported_parameters"
    assert byom.upstream.calls == []


@pytest.mark.parametrize("name", OUTSIDE_THE_CONTRACT)
def test_a_request_outside_the_text_contract_costs_no_key_read_and_no_upstream_call(
    byom: Harness, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    messages, code = OUTSIDE_THE_CONTRACT[name]
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        byom.upstream.calls.clear()
        reads = _key_reads(monkeypatch)
        response = _chat(client, {**chat_body(ENDPOINT_A), "messages": messages})

    assert (response.status_code, response.json()["detail"]["code"]) == (422, code)
    assert (reads, byom.upstream.calls) == ([], [])


def test_a_message_that_is_not_an_object_is_refused_by_the_shared_check_before_any_key_read(
    byom: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY its own test: the route's shared request check refuses this shape with a 400 before
    # `prepare_chat_body` runs; this pins that it, too, costs no key read and no upstream call.
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        byom.upstream.calls.clear()
        reads = _key_reads(monkeypatch)
        response = _chat(client, {**chat_body(ENDPOINT_A), "messages": ["ping"]})

    assert response.status_code == 400, response.text
    assert (reads, byom.upstream.calls) == ([], [])


def test_a_text_conversation_is_forwarded_unchanged(
    byom: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        reads = _key_reads(monkeypatch)
        response = _chat(client, {**chat_body(ENDPOINT_A), "messages": CONVERSATION})

    assert response.status_code == 200, response.text
    assert byom.upstream.bodies[-1] == {"model": UPSTREAM_MODEL, "messages": CONVERSATION}
    # WHY: proves the spy sees the key read that every refused request above never made.
    assert reads
