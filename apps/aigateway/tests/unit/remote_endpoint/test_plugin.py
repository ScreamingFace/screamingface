"""One adapter class, many endpoint instances: identity, credential addressing and chat dispatch.

# FEATURE: hosted BYOM Unit 0 — a configured endpoint is an ordinary provider instance; its key
# lives under its OWN provider ID and its traffic goes only to its own origin.
# INVARIANT: two instances built from the same class with the same upstream model name differ only
# by their definitions; no code path branches on a specific endpoint ID.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from aigateway.plugins.remote_endpoint.definitions import (
    EndpointDefinition,
    parse_remote_endpoint_config,
)
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .fixtures import (
    ALIAS,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    MALFORMED_COMPLETIONS,
    ORIGIN_A,
    ORIGIN_B,
    THIN_COMPLETIONS,
    UPSTREAM_MODEL,
    two_endpoint_document,
)

KEY = "sk-byom-plugin-key-0001"
COMPLETION = {
    "id": "chatcmpl-byom",
    "object": "chat.completion",
    "created": 1,
    "model": UPSTREAM_MODEL,
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}
    ],
}


def _definitions() -> tuple[EndpointDefinition, EndpointDefinition]:
    first, second = parse_remote_endpoint_config(two_endpoint_document()).endpoints
    return first, second


class _Recorder:
    """A fake upstream that records every request and answers from a script."""

    def __init__(self, respond: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond or (lambda _request: httpx.Response(200, json=COMPLETION))

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._respond(request)

        return httpx.MockTransport(handler)


def _body(model: str, **extra: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "ping"}], **extra}


def _code(exc: HTTPException) -> str:
    detail: Any = exc.detail
    return detail["code"]


# --- identity and credential addressing ----------------------------------------------------------


def test_each_instance_takes_its_identity_from_its_definition() -> None:
    first, second = (RemoteEndpointPlugin(d) for d in _definitions())

    assert type(first) is type(second)
    assert (first.custom_llm_provider, second.custom_llm_provider) == (ENDPOINT_A, ENDPOINT_B)
    assert first.provider_display_name == "Lab endpoint aaaa"
    assert first.available_auth_modes() == ("api_key",)
    assert first.credential_service_provider() == ENDPOINT_A
    assert [entry.model_name for entry in first.register_models()] == [f"{ENDPOINT_A}/{ALIAS}"]
    assert first.supports_chat_streaming() is False
    assert first.auth_router() is None


def test_the_key_is_addressed_under_the_instance_id_not_a_shared_namespace() -> None:
    first, second = (RemoteEndpointPlugin(d) for d in _definitions())
    name = "11111111-1111-4111-8111-111111111111:default"

    a_strategy = first.api_key_strategy_for(name)
    b_strategy = second.api_key_strategy_for(name)

    assert a_strategy.credential_service() == f"aigateway:{ENDPOINT_A}:{name}"
    assert b_strategy.credential_service() == f"aigateway:{ENDPOINT_B}:{name}"
    assert a_strategy.credential_account() == b_strategy.credential_account() == "default"


@pytest.mark.asyncio
async def test_the_strategy_builds_a_bearer_header_from_the_stored_key() -> None:
    (first, _) = (RemoteEndpointPlugin(d) for d in _definitions())

    class _Store:
        async def read(self, service: str, account: str) -> str | None:
            assert (service, account) == (f"aigateway:{ENDPOINT_A}:n", "default")
            return json.dumps({"auth_type": "api_key", "api_key": KEY, "origin": ORIGIN_A})

        # INVARIANT: resolving a header only reads; any write would be a bug.
        async def write(self, service: str, account: str, value: str) -> None:
            raise AssertionError("the strategy must not write")

        async def delete(self, service: str, account: str) -> None:
            raise AssertionError("the strategy must not delete")

        async def mutate(
            self, service: str, account: str, mutator: Callable[[str | None], str | None]
        ) -> None:
            raise AssertionError("the strategy must not mutate")

    strategy = first.api_key_strategy_for("n", credential_store=_Store())

    assert await strategy.get_authorization_header() == {"Authorization": f"Bearer {KEY}"}


def test_the_strategy_hook_takes_the_credential_name_by_keyword() -> None:
    # WHY by keyword: core names this hook's first parameter `credential_name` (OME-1209) and may
    # pass it by that keyword; an override under another name would raise TypeError there.
    (first, _) = (RemoteEndpointPlugin(d) for d in _definitions())

    strategy = first.api_key_strategy_for(credential_name="n")

    assert strategy.credential_service() == f"aigateway:{ENDPOINT_A}:n"


# --- chat body and dispatch ----------------------------------------------------------------------


def test_prepare_keeps_only_the_basic_chat_fields() -> None:
    (plugin, _) = (RemoteEndpointPlugin(d) for d in _definitions())
    hostile = _body(
        f"{ENDPOINT_A}/{ALIAS}",
        api_key="caller-key",
        api_base="https://attacker.byom.test",
        base_url="https://attacker.byom.test",
        extra_headers={"Authorization": "Bearer caller"},
        tools=[{"type": "function"}],
        stream=False,
    )

    assert plugin.prepare_chat_body(hostile) == _body(f"{ENDPOINT_A}/{ALIAS}")


@pytest.mark.parametrize("model", [f"{ENDPOINT_A}/absent", f"{ENDPOINT_B}/{ALIAS}", "", None])
def test_prepare_refuses_a_model_that_is_not_this_instances_target(model: Any) -> None:
    (plugin, _) = (RemoteEndpointPlugin(d) for d in _definitions())

    with pytest.raises(HTTPException) as caught:
        plugin.prepare_chat_body(_body(model))

    assert caught.value.status_code == 400
    assert _code(caught.value) == "invalid_model"


@pytest.mark.asyncio
async def test_two_instances_with_one_model_name_reach_only_their_own_origin() -> None:
    upstream = _Recorder()
    plugins = [RemoteEndpointPlugin(d, transport=upstream.transport()) for d in _definitions()]

    for plugin, key in zip(plugins, ("key-for-endpoint-a", "key-for-endpoint-b"), strict=True):
        body = plugin.prepare_chat_body(_body(f"{plugin.custom_llm_provider}/{ALIAS}"))
        body["api_key"] = key
        assert await plugin.chat_completion(body) == COMPLETION

    sent = [
        (str(r.url), r.headers["authorization"], json.loads(r.content)) for r in upstream.requests
    ]
    expected_payload = {"model": UPSTREAM_MODEL, "messages": [{"role": "user", "content": "ping"}]}
    assert sent == [
        (ORIGIN_A + CHAT_PATH, "Bearer key-for-endpoint-a", expected_payload),
        (ORIGIN_B + CHAT_PATH, "Bearer key-for-endpoint-b", expected_payload),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "", 7])
async def test_dispatch_without_a_resolved_key_sends_nothing(api_key: Any) -> None:
    upstream = _Recorder()
    (plugin, _) = (RemoteEndpointPlugin(d, transport=upstream.transport()) for d in _definitions())
    body = _body(f"{ENDPOINT_A}/{ALIAS}")
    if api_key is not None:
        body["api_key"] = api_key

    with pytest.raises(HTTPException):
        await plugin.chat_completion(body)

    assert upstream.requests == []


@pytest.mark.asyncio
async def test_dispatch_rechecks_the_target_before_sending() -> None:
    upstream = _Recorder()
    (plugin, _) = (RemoteEndpointPlugin(d, transport=upstream.transport()) for d in _definitions())

    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(_body(f"{ENDPOINT_A}/absent", api_key=KEY))

    assert caught.value.status_code == 400
    assert upstream.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, status, code",
    [
        (httpx.Response(401, json={"error": "secret upstream text"}), 502, "provider_error"),
        (httpx.Response(500, text="secret upstream text"), 502, "provider_error"),
        (httpx.Response(429, headers={"retry-after": "7"}), 429, "provider_error"),
        (httpx.Response(503), 503, "provider_error"),
        (
            httpx.Response(302, headers={"location": "https://other.byom.test/"}),
            502,
            "provider_error",
        ),
        (httpx.Response(200, text="not json"), 502, "provider_error"),
        (httpx.Response(200, json={"no": "choices"}), 502, "provider_error"),
        (
            httpx.Response(
                200, content=b"x" * 1_000_001, headers={"content-type": "application/json"}
            ),
            502,
            "provider_error",
        ),
    ],
)
async def test_upstream_failures_are_sanitized(
    response: httpx.Response, status: int, code: str
) -> None:
    upstream = _Recorder(lambda _request: response)
    (plugin, _) = (RemoteEndpointPlugin(d, transport=upstream.transport()) for d in _definitions())

    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(_body(f"{ENDPOINT_A}/{ALIAS}", api_key=KEY))

    assert (caught.value.status_code, _code(caught.value)) == (status, code)
    assert "secret upstream text" not in json.dumps(caught.value.detail)
    # INVARIANT: a redirect is never followed, so a key cannot be replayed to another host.
    assert len(upstream.requests) == 1
    if status == 429:
        assert caught.value.headers == {"Retry-After": "7"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b'{"choices": [NaN]}',
        b'[{"choices": [1]}]',
        b'{"choices": [' + b"[" * 200 + b"]" * 200 + b"]}",
    ],
    ids=["malformed", "non-finite", "not-an-object", "too-deep"],
)
async def test_a_json_typed_body_that_is_not_a_bounded_completion_is_refused(
    content: bytes,
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"content-type": "application/json"})

    upstream = _Recorder(respond)
    (plugin, _) = (RemoteEndpointPlugin(d, transport=upstream.transport()) for d in _definitions())

    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(_body(f"{ENDPOINT_A}/{ALIAS}", api_key=KEY))

    assert (caught.value.status_code, _code(caught.value)) == (502, "provider_error")


@pytest.mark.asyncio
async def test_a_transport_failure_is_reported_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    (plugin, _) = (
        RemoteEndpointPlugin(d, transport=httpx.MockTransport(fail)) for d in _definitions()
    )

    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(_body(f"{ENDPOINT_A}/{ALIAS}", api_key=KEY))

    assert (caught.value.status_code, _code(caught.value)) == (502, "provider_unavailable")


def _answering(body: dict[str, Any]) -> tuple[RemoteEndpointPlugin, _Recorder]:
    upstream = _Recorder(lambda _request: httpx.Response(200, json=body))
    (plugin, _) = (RemoteEndpointPlugin(d, transport=upstream.transport()) for d in _definitions())
    return plugin, upstream


@pytest.mark.asyncio
@pytest.mark.parametrize("body", MALFORMED_COMPLETIONS.values(), ids=MALFORMED_COMPLETIONS.keys())
async def test_dispatch_refuses_a_200_that_is_not_a_completion(body: dict[str, Any]) -> None:
    plugin, upstream = _answering(body)

    with pytest.raises(HTTPException) as caught:
        await plugin.chat_completion(_body(f"{ENDPOINT_A}/{ALIAS}", api_key=KEY))

    assert (caught.value.status_code, _code(caught.value)) == (502, "provider_error")
    assert len(upstream.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", THIN_COMPLETIONS.values(), ids=THIN_COMPLETIONS.keys())
async def test_dispatch_returns_a_thin_but_well_formed_completion(body: dict[str, Any]) -> None:
    plugin, _ = _answering(body)

    assert await plugin.chat_completion(_body(f"{ENDPOINT_A}/{ALIAS}", api_key=KEY)) == body
