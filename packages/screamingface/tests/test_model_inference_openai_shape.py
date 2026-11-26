"""MI-37: client.chat and aclient.chat have the OpenAI call path, with model as a required keyword
(D11, D13; contracts C1.1, C1.2, C1.5). MI-32 to MI-35 are rewritten for this surface.

STORY: as a user of the OpenAI SDK, I keep my
client.chat.completions.create(model=..., messages=...) calls, and they run an SDK ensemble.
"""

from __future__ import annotations

from typing import Any, assert_type, cast

import httpx
import pytest
from _chat_engine import (
    BENCH_ROUTE,
    CAND,
    ENGINE_URL,
    EVAL,
    model,
    ok,
    recording_client,
    sent_body,
)
from _chat_stream import async_recording_client

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.chat_completion import ChatCompletion, ChatStream
from screamingface.client import AsyncClient, Client
from screamingface.errors import PlanningError
from screamingface.inference import AsyncChat, AsyncCompletions, Chat, Completions

MESSAGES = [{"role": "user", "content": "Hello"}]


def test_the_call_path_is_chat_completions_create() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        assert isinstance(client.chat, Chat)
        assert isinstance(client.chat.completions, Completions)
        assert not hasattr(client.chat, "complete")
        assert client.chat is client.chat
        assert client.chat._client is client

    assert requests == []


@pytest.mark.asyncio
async def test_the_async_call_path_is_chat_completions_create() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        assert isinstance(aclient.chat, AsyncChat)
        assert isinstance(aclient.chat.completions, AsyncCompletions)
        assert aclient.chat._client is aclient

    assert requests == []


def test_each_call_gives_its_model() -> None:
    # INVARIANT (D12): the OpenAI call form runs with no change after the client line.
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        reply = client.chat.completions.create(model="openrouter/a", messages=MESSAGES)
        client.chat.completions.create(model=model(), messages=MESSAGES)

    assert isinstance(reply, ChatCompletion)
    assert sent_body(requests[0])["model"] == "openrouter/a"
    assert sent_body(requests[1])["model"] == compile_candidate(model()).url4
    assert sent_body(requests[0])["messages"] == MESSAGES


def test_two_calls_on_one_client_send_their_own_model() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        client.chat.completions.create("Hello", model="openrouter/b")
        client.chat.completions.create("Hello", model="openrouter/a")

    assert [sent_body(r)["model"] for r in requests] == ["openrouter/b", "openrouter/a"]


def test_model_is_a_required_keyword() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        with pytest.raises(TypeError, match="model"):
            cast(Any, client.chat.completions).create(messages=MESSAGES)

    assert requests == []


@pytest.mark.parametrize(("value", "error"), [(42, TypeError), ("  ", ValueError)])
def test_a_wrong_model_of_a_call_raises_before_a_request(
    value: object, error: type[Exception]
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        with pytest.raises(error):
            client.chat.completions.create("Hello", model=cast(Any, value))

    assert requests == []


def test_the_model_rules_apply_at_each_call() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        client.chat.completions.create("Hello", model=sf.Url4(EVAL))
        with pytest.raises(PlanningError) as raised:
            client.chat.completions.create("Hello", model=BENCH_ROUTE)

    assert sent_body(requests[0])["model"] == CAND
    assert raised.value.code == "recipe_invalid"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_client_takes_the_model_of_each_call() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        reply = await aclient.chat.completions.create(model="openrouter/a", messages=MESSAGES)
        await aclient.chat.completions.create(model=model(), messages=MESSAGES)

    assert isinstance(reply, ChatCompletion)
    assert sent_body(requests[0])["model"] == "openrouter/a"
    assert sent_body(requests[1])["model"] == compile_candidate(model()).url4
    assert sent_body(requests[0])["messages"] == MESSAGES


@pytest.mark.asyncio
async def test_async_model_is_a_required_keyword_raised_by_the_call() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        # AIDEV-NOTE: the TypeError comes from the call itself, so no coroutine is made.
        with pytest.raises(TypeError, match="model"):
            _ = cast(Any, aclient.chat.completions).create(messages=MESSAGES)
        with pytest.raises(TypeError):
            _ = aclient.chat.completions.create("Hello", model=cast(Any, 42))

    assert requests == []


def test_endpoint_takes_the_model_of_the_call() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        e = client.chat.endpoint("openrouter/b")
        other = client.chat.endpoint("openrouter/a")

    assert e.model == "openrouter/b"
    assert other.model == "openrouter/a"
    assert e.base_url == f"{ENGINE_URL}/v1"
    assert requests == []


def test_endpoint_with_no_model_raises_type_error() -> None:
    with recording_client(ok, []) as client:
        with pytest.raises(TypeError):
            cast(Any, client.chat).endpoint()


@pytest.mark.asyncio
async def test_async_endpoint_takes_the_model_of_the_call() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        e = await aclient.chat.endpoint("openrouter/b")

    assert e.model == "openrouter/b"
    assert e.base_url == f"{ENGINE_URL}/v1"
    assert requests == []


def test_the_chat_access_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        _ = client.chat
        _ = client.chat.completions
        _ = sf.Model("openrouter/a").chat

    assert requests == []


def _typed_calls(client: Client, aclient: AsyncClient) -> None:
    """Pyright checks these types (MI-27): the call with model= keeps the typed overloads."""

    assert_type(client.chat, Chat)
    assert_type(client.chat.completions, Completions)
    assert_type(client.chat.completions.create(model="m", messages=MESSAGES), ChatCompletion)
    assert_type(
        client.chat.completions.create(model="m", messages=MESSAGES, stream=True), ChatStream
    )
    assert_type(aclient.chat, AsyncChat)
    assert_type(aclient.chat.completions, AsyncCompletions)
