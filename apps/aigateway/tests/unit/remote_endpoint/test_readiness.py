"""The per-instance key readiness probe behind the existing validation service.

# FEATURE: hosted BYOM Unit 0 — attaching a key runs one bounded synthetic chat request against the
# instance's own validation target, through the shared `ApiKeyValidationService`.
# INVARIANT: the probe goes to the instance's origin and fixed path with exactly the supplied key,
# and only a well-formed success is VALID at READINESS.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import httpx
import pytest

from aigateway.core.api_key_validation import ApiKeyValidationStage, ApiKeyValidationState
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .fixtures import (
    ALIAS,
    CHAT_PATH,
    ENDPOINT_A,
    MALFORMED_COMPLETIONS,
    ORIGIN_A,
    THIN_COMPLETIONS,
    UPSTREAM_MODEL,
    two_endpoint_document,
)

KEY = "sk-byom-readiness-0001"
_OK = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "."}}]}


def _plugin(respond: Any, sent: list[httpx.Request]) -> RemoteEndpointPlugin:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(request)

    definition = parse_remote_endpoint_config(two_endpoint_document()).endpoints[0]
    return RemoteEndpointPlugin(definition, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_successful_probe_is_valid_at_readiness_through_the_service() -> None:
    sent: list[httpx.Request] = []
    plugin = _plugin(lambda _r: httpx.Response(200, json=_OK), sent)

    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)

    assert result is not None
    assert (result.state, result.stage) == (
        ApiKeyValidationState.VALID,
        ApiKeyValidationStage.READINESS,
    )
    assert result.probe_model == f"{ENDPOINT_A}/{ALIAS}"
    (request,) = sent
    assert (request.method, str(request.url)) == ("POST", ORIGIN_A + CHAT_PATH)
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "model": UPSTREAM_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, state",
    [
        (httpx.Response(401), ApiKeyValidationState.INVALID),
        (httpx.Response(402), ApiKeyValidationState.NO_QUOTA),
        (httpx.Response(403), ApiKeyValidationState.PERMISSION_DENIED),
        (httpx.Response(429, headers={"retry-after": "9"}), ApiKeyValidationState.RATE_LIMITED),
        (httpx.Response(500), ApiKeyValidationState.UNAVAILABLE),
        (httpx.Response(503), ApiKeyValidationState.UNAVAILABLE),
        (
            httpx.Response(302, headers={"location": "https://x.byom.test/"}),
            ApiKeyValidationState.UNAVAILABLE,
        ),
        (httpx.Response(200, json={"no": "choices"}), ApiKeyValidationState.UNAVAILABLE),
    ],
)
async def test_probe_outcomes_map_to_validation_states(
    response: httpx.Response, state: ApiKeyValidationState
) -> None:
    sent: list[httpx.Request] = []
    plugin = _plugin(lambda _r: response, sent)

    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)

    assert result is not None
    assert result.state is state
    assert result.stage is ApiKeyValidationStage.READINESS
    assert len(sent) == 1
    if state is ApiKeyValidationState.RATE_LIMITED:
        assert result.retry_after_seconds == 9


@pytest.mark.asyncio
async def test_a_transport_failure_is_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = await ApiKeyValidationService().validate(_plugin(fail, []), ENDPOINT_A, KEY)

    assert result is not None
    assert result.state is ApiKeyValidationState.UNAVAILABLE


@pytest.mark.asyncio
async def test_a_definition_whose_validation_target_is_missing_is_misconfigured() -> None:
    # WHY build it by hand: the parser refuses this shape, so only a hand-built definition reaches
    # the guard; it must report MISCONFIGURED and send nothing rather than guess a target.
    sent: list[httpx.Request] = []
    definition = parse_remote_endpoint_config(two_endpoint_document()).endpoints[0]
    broken = dataclasses.replace(definition, validation_target="absent")

    result = (
        await RemoteEndpointPlugin(
            broken, transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200))
        )
        .api_key_validator()
        .validate(KEY)
    )

    assert result.state is ApiKeyValidationState.MISCONFIGURED
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", MALFORMED_COMPLETIONS.values(), ids=MALFORMED_COMPLETIONS.keys())
async def test_a_200_that_is_not_a_completion_is_unavailable_not_valid(
    body: dict[str, Any],
) -> None:
    # INVARIANT: VALID publishes the key, so it needs a real completion, not merely a 200.
    sent: list[httpx.Request] = []
    plugin = _plugin(lambda _r: httpx.Response(200, json=body), sent)

    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)

    assert result is not None
    assert (result.state, result.stage) == (
        ApiKeyValidationState.UNAVAILABLE,
        ApiKeyValidationStage.READINESS,
    )
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", THIN_COMPLETIONS.values(), ids=THIN_COMPLETIONS.keys())
async def test_a_thin_but_well_formed_completion_is_valid(body: dict[str, Any]) -> None:
    plugin = _plugin(lambda _r: httpx.Response(200, json=body), [])

    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)

    assert result is not None
    assert result.state is ApiKeyValidationState.VALID


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"Too Many Requests"], ids=["empty", "plaintext"])
@pytest.mark.parametrize(
    "status, state",
    [
        (401, ApiKeyValidationState.INVALID),
        (429, ApiKeyValidationState.RATE_LIMITED),
    ],
)
async def test_an_error_status_is_classified_whatever_its_body(
    status: int, state: ApiKeyValidationState, body: bytes
) -> None:
    # INVARIANT: a plaintext error body classifies exactly as an empty one; a rate limit keeps
    # its Retry-After hint.
    headers = {"retry-after": "30"}
    plugin = _plugin(lambda _r: httpx.Response(status, headers=headers, content=body), [])

    result = await ApiKeyValidationService().validate(plugin, ENDPOINT_A, KEY)

    assert result is not None
    hint = 30 if state is ApiKeyValidationState.RATE_LIMITED else None
    assert (result.state, result.retry_after_seconds) == (state, hint)
