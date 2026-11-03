"""The classification POST to a configured endpoint, through the chat path's transport.

# FEATURE: hosted BYOM Unit 3 — the Gateway sends `{"inputs": <input>}` to `origin + request_path`
# with the Connection's bearer key, over the endpoint's one client, and reads a bounded answer.
# INVARIANT: a status other than 200 maps exactly as it does for chat; a redirect is not followed;
# neither the key nor the input crosses into any error.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .classifier_upstream import SCORES, classifier_id, mixed_document
from .fixtures import ALIAS, CLASSIFIER_PATH, ENDPOINT_A, FINISHED_COMPLETION, JSON_TYPE, ORIGIN_A

KEY = "sk-byom-classify-transport-0001"
TEXT = 'Line one\nline "two" + three: café, 東京, 🙂 & 100%'


def _plugin(respond: Callable[[httpx.Request], httpx.Response]) -> RemoteEndpointPlugin:
    definition = parse_remote_endpoint_config(mixed_document()).endpoints[0]
    return RemoteEndpointPlugin(definition, transport=httpx.MockTransport(respond))


def _request(text: str = TEXT) -> dict[str, Any]:
    return {"model": classifier_id(ENDPOINT_A), "input": text, "api_key": KEY}


def _chat_request() -> dict[str, Any]:
    return {
        "model": f"{ENDPOINT_A}/{ALIAS}",
        "messages": [{"role": "user", "content": "ping"}],
        "api_key": KEY,
    }


def _code(exc: HTTPException) -> str:
    detail: Any = exc.detail
    return detail["code"]


def _assert_private(exc: HTTPException) -> None:
    text = f"{exc.detail!r} {exc.headers!r}"
    assert KEY not in text
    assert TEXT not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [TEXT, "", " ", "+", "a\r\nb", "\\u0000", "\u00a0"])
async def test_the_exact_url_bearer_and_body_are_sent(text: str) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[SCORES])

    result = await _plugin(respond).classify(_request(text))

    (request,) = seen
    assert (request.method, str(request.url)) == ("POST", ORIGIN_A + CLASSIFIER_PATH)
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["accept-encoding"] == "identity"
    assert json.loads(request.content) == {"inputs": text}
    assert result == {
        "object": "classification",
        "model": classifier_id(ENDPOINT_A),
        "contract": "classification-scores-v1",
        "scores": SCORES,
    }


@pytest.mark.asyncio
async def test_the_flat_envelope_is_read_when_configured() -> None:
    definition = parse_remote_endpoint_config(mixed_document(envelope="flat")).endpoints[0]

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SCORES)

    plugin = RemoteEndpointPlugin(definition, transport=httpx.MockTransport(respond))

    assert (await plugin.classify(_request()))["scores"] == SCORES


async def _failure(plugin: RemoteEndpointPlugin, body: dict[str, Any]) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        if "input" in body:
            await plugin.classify(body)
        else:
            await plugin.chat_completion(body)
    return caught.value


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 204, 400, 401, 402, 403, 404, 413, 429, 500, 502, 503])
@pytest.mark.parametrize("hint", [None, "7", "9" * 20])
async def test_a_status_other_than_200_maps_as_it_does_for_chat(
    status: int, hint: str | None
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        headers = {} if hint is None else {"retry-after": hint}
        return httpx.Response(status, headers=headers, json={"error": f"{KEY} {TEXT}"})

    plugin = _plugin(respond)
    classified = await _failure(plugin, _request())
    chatted = await _failure(plugin, _chat_request())

    assert (classified.status_code, classified.detail, classified.headers) == (
        chatted.status_code,
        chatted.detail,
        chatted.headers,
    )
    _assert_private(classified)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_a_redirect_is_not_followed(status: int) -> None:
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, headers={"location": "https://elsewhere.test/steal"})

    failure = await _failure(_plugin(respond), _request())

    assert (failure.status_code, _code(failure)) == (502, "provider_error")
    assert seen == [ORIGIN_A + CLASSIFIER_PATH]


class _Endless(httpx.AsyncByteStream):
    """A body with no length header that never ends; it counts what was read."""

    def __init__(self, chunk: bytes) -> None:
        self.chunk = chunk
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            self.read += len(self.chunk)
            yield self.chunk


@pytest.mark.asyncio
async def test_a_body_without_a_length_is_aborted_near_the_cap() -> None:
    body = _Endless(b"[" + b" " * 65_535)

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": JSON_TYPE}, stream=body)

    failure = await _failure(_plugin(respond), _request())

    assert (failure.status_code, _code(failure)) == (502, "provider_error")
    assert 1_000_000 < body.read <= 1_000_000 + 2 * 65_536


@pytest.mark.asyncio
async def test_an_encoded_answer_is_refused() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        headers = {"content-type": JSON_TYPE, "content-encoding": "gzip"}
        body = httpx.ByteStream(gzip.compress(json.dumps([SCORES]).encode()))
        return httpx.Response(200, headers=headers, stream=body)

    failure = await _failure(_plugin(respond), _request())

    assert (failure.status_code, _code(failure)) == (502, "provider_error")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, json=[[{"label": KEY, "score": 2}]]),
        httpx.Response(200, json=FINISHED_COMPLETION),
        httpx.Response(200, content=TEXT.encode(), headers={"content-type": "text/plain"}),
    ],
    ids=["out-of-range", "chat-completion", "text"],
)
async def test_a_malformed_answer_is_a_sanitized_failure(answer: httpx.Response) -> None:
    failure = await _failure(_plugin(lambda _request: answer), _request())

    assert (failure.status_code, _code(failure)) == (502, "provider_error")
    _assert_private(failure)


@pytest.mark.asyncio
async def test_a_transport_failure_is_a_sanitized_failure() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} with {KEY} for {TEXT}")

    failure = await _failure(_plugin(respond), _request())

    assert (failure.status_code, _code(failure)) == (502, "provider_unavailable")
    _assert_private(failure)


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, ""])
async def test_no_resolved_key_is_refused_without_a_request(api_key: str | None) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[SCORES])

    body = {**_request(), "api_key": api_key}
    failure = await _failure(_plugin(respond), body)

    assert (failure.status_code, _code(failure)) == (503, "provider_unavailable")
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", [ALIAS, "undeclared_v1"])
async def test_a_model_that_is_no_classifier_is_refused_without_a_request(alias: str) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[SCORES])

    body = {**_request(), "model": f"{ENDPOINT_A}/{alias}"}
    failure = await _failure(_plugin(respond), body)

    assert (failure.status_code, _code(failure)) == (400, "invalid_model")
    assert seen == []
