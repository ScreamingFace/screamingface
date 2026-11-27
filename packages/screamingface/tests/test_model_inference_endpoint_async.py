"""EB-5 and the async half of EB-2, EB-4 and EB-6: endpoint() with an AsyncClient (ans:Q7)."""

from __future__ import annotations

import inspect

import httpx
import pytest
from _chat_engine import CATALOG, ENGINE_URL, catalogue_engine, ok, vote
from _chat_stream import async_recording_client
from _endpoint_access import (
    HOSTED_URL,
    TOKEN_HEADER,
    async_hosted_client,
    fake_access,
    no_access,
    signed_in,
)

from screamingface._evaluation.candidate import compile_candidate
from screamingface.errors import AuthenticationError, EngineCapabilityError
from screamingface.inference import InferenceEndpoint


@pytest.mark.asyncio
async def test_endpoint_is_awaitable_with_an_async_client() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        call = aclient.chat.endpoint("openrouter/a")
        assert inspect.iscoroutine(call)
        e = await call

    assert isinstance(e, InferenceEndpoint)
    assert e.base_url == f"{ENGINE_URL}/v1"
    assert e.model == "openrouter/a"
    assert dict(e.headers) == {}
    assert requests == []


@pytest.mark.asyncio
async def test_async_endpoint_values_for_a_hosted_client(monkeypatch: pytest.MonkeyPatch) -> None:
    token, browser = signed_in(monkeypatch)
    requests: list[httpx.Request] = []
    async with async_hosted_client(ok, requests) as aclient:
        e = await aclient.chat.endpoint("openrouter/a")

    assert e.base_url == f"{HOSTED_URL}/v1"
    assert dict(e.headers) == {TOKEN_HEADER: token}
    assert token not in repr(e)
    assert browser == []
    assert requests == []


@pytest.mark.asyncio
async def test_async_endpoint_loads_the_catalogue_for_a_reducer_recipe() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(catalogue_engine, requests) as aclient:
        e = await aclient.chat.endpoint(vote())

    assert e.model == compile_candidate(vote(), operators=CATALOG).url4
    assert [r.url.path for r in requests] == ["/v1/operators"]


@pytest.mark.asyncio
async def test_async_endpoint_failure_gives_no_partial_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = fake_access(monkeypatch, no_access)
    requests: list[httpx.Request] = []
    async with async_hosted_client(catalogue_engine, requests) as aclient:
        with pytest.raises(AuthenticationError) as raised:
            await aclient.chat.endpoint(vote())

    assert raised.value.code == "access_not_advertised"
    assert requests == []
    assert browser == []


@pytest.mark.asyncio
async def test_async_endpoint_raises_the_catalogue_error() -> None:
    def not_found(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    requests: list[httpx.Request] = []
    async with async_recording_client(not_found, requests) as aclient:
        with pytest.raises(EngineCapabilityError):
            await aclient.chat.endpoint(vote())

    assert [r.url.path for r in requests] == ["/v1/operators"]


@pytest.mark.asyncio
async def test_async_closed_client_raises_before_a_coroutine() -> None:
    requests: list[httpx.Request] = []
    aclient = async_recording_client(ok, requests)
    await aclient.aclose()
    with pytest.raises(RuntimeError, match="AsyncClient is closed"):
        _ = aclient.chat.endpoint("openrouter/a")

    assert requests == []
