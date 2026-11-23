"""MI-32 to MI-35: the OpenAI client shape of InferenceClient (D11, D12; contracts C1.1-C1.5).

STORY: as a user of the OpenAI SDK, I change only the line that makes the client, and my
``client.chat.completions.create(model=..., messages=...)`` calls run an SDK ensemble.
"""

from __future__ import annotations

from typing import assert_type

import httpx
import pytest
from _chat_engine import ENGINE_URL, model, ok, recording_client, sent_body
from _chat_stream import async_recording_client

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.chat_completion import ChatCompletion, ChatStream
from screamingface.client import AsyncClient, Client
from screamingface.inference import Chat, Completions, InferenceClient

MESSAGES = [{"role": "user", "content": "Hello"}]


def test_the_call_path_is_chat_completions_create() -> None:
    llm = InferenceClient("openrouter/a")

    assert isinstance(llm.chat, Chat)
    assert isinstance(llm.chat.completions, Completions)
    assert not hasattr(llm.chat, "complete")


def test_a_client_with_no_model_takes_the_model_of_each_call() -> None:
    # INVARIANT (D12): the OpenAI call form runs with no change after the client line.
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = InferenceClient(client=client)
        reply = llm.chat.completions.create(model="openrouter/a", messages=MESSAGES)
        llm.chat.completions.create(model=model(), messages=MESSAGES)

    assert isinstance(reply, ChatCompletion)
    assert sent_body(requests[0])["model"] == "openrouter/a"
    assert sent_body(requests[1])["model"] == compile_candidate(model()).url4
    assert sent_body(requests[0])["messages"] == MESSAGES


def test_the_model_of_a_call_replaces_the_model_of_the_client_for_that_call_only() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = InferenceClient("openrouter/a", client=client)
        llm.chat.completions.create("Hello", model="openrouter/b")
        llm.chat.completions.create("Hello")

    assert [sent_body(r)["model"] for r in requests] == ["openrouter/b", "openrouter/a"]


def test_no_model_on_the_client_or_the_call_raises_type_error_before_a_request() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = InferenceClient(client=client)
        with pytest.raises(TypeError, match="give a model"):
            llm.chat.completions.create(messages=MESSAGES)

    assert requests == []


@pytest.mark.parametrize(("value", "error"), [(42, TypeError), ("  ", ValueError)])
def test_a_wrong_model_of_a_call_raises_before_a_request(
    value: object, error: type[Exception]
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = InferenceClient("openrouter/a", client=client)
        with pytest.raises(error):
            llm.chat.completions.create("Hello", model=value)  # type: ignore[arg-type]

    assert requests == []


@pytest.mark.asyncio
async def test_async_client_takes_the_model_of_each_call() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        llm = InferenceClient(client=aclient)
        reply = await llm.chat.completions.create(model="openrouter/a", messages=MESSAGES)

    assert isinstance(reply, ChatCompletion)
    assert sent_body(requests[0])["model"] == "openrouter/a"


@pytest.mark.asyncio
async def test_async_client_with_no_model_raises_before_a_coroutine_exists() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        llm = InferenceClient(client=aclient)
        with pytest.raises(TypeError, match="give a model"):
            _ = llm.chat.completions.create(messages=MESSAGES)

    assert requests == []


def test_endpoint_takes_the_model_of_the_call() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = InferenceClient("openrouter/a", client=client)
        e = llm.endpoint(model="openrouter/b")
        default = llm.endpoint()

    assert e.model == "openrouter/b"
    assert default.model == "openrouter/a"
    assert e.base_url == f"{ENGINE_URL}/v1"


def test_endpoint_with_no_model_raises_type_error() -> None:
    with recording_client(ok, []) as client:
        with pytest.raises(TypeError, match="give a model"):
            InferenceClient(client=client).endpoint()


def test_the_constructor_with_no_model_sends_no_request() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        InferenceClient(client=client)
        InferenceClient(sf.Model("openrouter/a"), client=client)

    assert requests == []


def _typed_calls(client: Client, aclient: AsyncClient) -> None:
    """Pyright checks these types (MI-27): the call with model= keeps the typed overloads."""

    llm = InferenceClient(client=client)
    assert_type(llm.chat.completions, Completions[Client])
    assert_type(llm.chat.completions.create(model="m", messages=MESSAGES), ChatCompletion)
    assert_type(llm.chat.completions.create(model="m", messages=MESSAGES, stream=True), ChatStream)
    allm = InferenceClient(client=aclient)
    assert_type(allm.chat.completions, Completions[AsyncClient])
