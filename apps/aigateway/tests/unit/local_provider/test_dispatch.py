from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import HTTPException

from aigateway.core.parameter_discovery import RawResponse
from aigateway.core.retry import is_retryable_status
from aigateway.plugins.local_provider.plugin import LocalProviderPlugin
from aigateway.plugins.local_provider.settings import LocalPluginSettings


class _DiscoveryClient:
    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        del url, timeout_s, max_bytes
        return RawResponse(
            status=200,
            content_type="application/json",
            body=json.dumps({"object": "list", "data": [{"id": "fixture:model"}]}),
        )


def _nested(depth: int) -> object:
    value: object = "deep"
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.asyncio
async def test_dispatch_restores_upstream_id_and_sends_no_auth_or_controls() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "chatcmpl-local",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture:model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(handler),
    )
    await plugin.discover_live_models(client=_DiscoveryClient())
    prepared = plugin.prepare_chat_body(
        {
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
            "api_key": "caller-secret",
            "api_base": "http://attacker.invalid/v1",
            "base_url": "http://attacker.invalid/v1",
            "headers": {"Authorization": "Bearer caller-secret"},
            "extra_headers": {"X-Api-Key": "caller-secret"},
            "num_retries": 9,
            "max_retries": 9,
        }
    )

    result = await plugin.chat_completion(prepared)

    assert result["choices"][0]["message"]["content"] == "pong"
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "authorization" not in headers
    assert "proxy-authorization" not in headers
    assert "x-api-key" not in headers
    assert captured["body"] == {
        "model": "fixture:model",
        "messages": [{"role": "user", "content": "ping"}],
    }
    assert captured["timeout"] == {
        "connect": None,
        "read": None,
        "write": None,
        "pool": None,
    }


@pytest.mark.asyncio
async def test_dispatch_accepts_a_valid_model_before_catalog_discovery() -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pong"}}]},
        )

    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(respond),
    )

    result = await plugin.chat_completion(
        {
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert result["choices"][0]["message"]["content"] == "pong"
    assert calls == ["fixture:model"]


@pytest.mark.asyncio
async def test_disabled_provider_refuses_chat_without_egress() -> None:
    calls = 0

    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=False),
        transport=httpx.MockTransport(fail_if_called),
    )

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {
                "model": "local/fixture:model",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == {
        "code": "provider_unavailable",
        "message": "The local model provider is disabled.",
    }
    assert calls == 0


@pytest.mark.parametrize("model", ["local/bad~id", "local/space id", "other/model", "local/"])
@pytest.mark.asyncio
async def test_dispatch_refuses_an_invalid_local_model_id(model: str) -> None:
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {"model": model, "messages": [{"role": "user", "content": "ping"}]}
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == {
        "code": "invalid_model",
        "message": "model is not a valid local model id",
    }


@pytest.mark.asyncio
async def test_upstream_errors_are_sanitized() -> None:
    secret = "UPSTREAM-SECRET-BODY"
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                headers={"content-type": "text/plain"},
                text=secret,
            )
        ),
    )
    await plugin.discover_live_models(client=_DiscoveryClient())

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {
                "model": "local/fixture:model",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "provider_error",
        "message": "The local model server returned an error.",
    }
    assert secret not in str(exc.value.detail)


@pytest.mark.parametrize(("status", "retryable"), [(400, False), (429, True), (503, True)])
@pytest.mark.asyncio
async def test_upstream_status_survives_with_a_sanitized_body(
    status: int,
    retryable: bool,
) -> None:
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                status,
                headers={"Retry-After": "7"},
                text="UPSTREAM-SECRET",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {
                "model": "local/fixture:model",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert exc.value.status_code == status
    assert exc.value.detail == {
        "code": "provider_error",
        "message": "The local model server returned an error.",
    }
    assert exc.value.headers == {"Retry-After": "7"}
    assert is_retryable_status(exc.value) is retryable
    assert "UPSTREAM-SECRET" not in str(exc.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, headers={"content-type": "text/plain"}, text="not json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": "not-an-object"}]}),
        httpx.Response(200, json={"choices": [{"message": {}}]}),
        httpx.Response(200, json={"choices": [{"message": {"reasoning": None}}]}),
        httpx.Response(200, json={"choices": [{"message": {"tool_calls": [None]}}]}),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "lookup"},
                                }
                            ]
                        }
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(b'{"choices":[{"message":{"content":"pong"}}],"usage":{"total_tokens":NaN}}'),
        ),
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(
                b'{"choices":[{"message":{"content":"pong"}}],"usage":{"total_tokens":1e999}}'
            ),
        ),
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "pong"}}],
                "extra": _nested(20),
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_success_responses_are_refused(response: httpx.Response) -> None:
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(lambda _request: response),
    )
    await plugin.discover_live_models(client=_DiscoveryClient())

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {
                "model": "local/fixture:model",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "provider_error",
        "message": "The local model response is invalid.",
    }


@pytest.mark.parametrize(
    "message",
    [
        {"role": "assistant", "content": None},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": None, "reasoning": "thinking"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
    ],
)
@pytest.mark.asyncio
async def test_openai_contentless_choices_cross_the_gateway_unchanged(
    message: dict[str, object],
) -> None:
    response = {
        "choices": [{"message": message, "finish_reason": "length"}],
    }
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
    )

    result = await plugin.chat_completion(
        {
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert result == response


@pytest.mark.asyncio
async def test_empty_tool_calls_is_equivalent_to_an_absent_field() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "pong",
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }
        ]
    }
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
    )

    result = await plugin.chat_completion(
        {
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        }
    )

    assert result == response


class _OversizedStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 300_000


@pytest.mark.asyncio
async def test_oversized_response_is_refused_while_streaming() -> None:
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_OversizedStream(),
            )
        ),
    )
    await plugin.discover_live_models(client=_DiscoveryClient())

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {
                "model": "local/fixture:model",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "code": "provider_error",
        "message": "The local model response is invalid.",
    }


@pytest.mark.asyncio
async def test_response_with_too_many_json_nodes_is_refused() -> None:
    plugin = LocalProviderPlugin(
        LocalPluginSettings(enabled=True),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "pong"}}],
                    "extra": [0] * 50_001,
                },
            )
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await plugin.chat_completion(
            {
                "model": "local/fixture:model",
                "messages": [{"role": "user", "content": "ping"}],
            }
        )

    assert exc.value.detail == {
        "code": "provider_error",
        "message": "The local model response is invalid.",
    }
