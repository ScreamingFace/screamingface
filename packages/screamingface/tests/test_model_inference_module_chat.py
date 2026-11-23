"""MI-38: the module sf.chat is the twin of client.chat for the default client.

WHY: contracts C1.1 and D15 name sf.chat as the same surface, with no client object.

STORY: as an SDK user, I call sf.chat.completions.create(model=..., ...) as I call sf.models.list(),
with no client object.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Iterator
from typing import Any, assert_type, cast

import httpx
import pytest
from _chat_engine import (
    CAND,
    CATALOG,
    CHAT_PATH,
    ENGINE_URL,
    catalogue_engine,
    fusion,
    model,
    recording_client,
    sent_body,
    vote,
)

import screamingface as sf
from screamingface import _default_client
from screamingface import chat as chat_module
from screamingface._evaluation.candidate import compile_candidate
from screamingface.chat_completion import ChatCompletion, ChatStream
from screamingface.errors import PlanningError
from screamingface.inference import InferenceEndpoint
from screamingface.warnings import IgnoredParameterWarning


@pytest.fixture
def default(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    requests: list[httpx.Request] = []
    client = recording_client(catalogue_engine, requests)
    monkeypatch.setattr(_default_client, "_client", client)
    yield requests
    if not client.closed:
        client.close()


def _no_default() -> sf.Client:
    raise AssertionError("the call made the default client")


def test_sf_chat_is_the_module() -> None:
    assert sf.chat is chat_module
    assert isinstance(sf.chat, types.ModuleType)
    assert "chat" in sf.__all__
    assert sf.chat.__all__ == ["completions", "endpoint"]


def test_create_goes_to_the_default_client(default: list[httpx.Request]) -> None:
    reply = sf.chat.completions.create("Hello", model="openrouter/a")

    assert isinstance(reply, ChatCompletion)
    assert reply.text == "Hello"
    [chat] = [r for r in default if r.url.path == CHAT_PATH]
    assert sent_body(chat)["model"] == "openrouter/a"
    assert sent_body(chat)["messages"] == [{"role": "user", "content": "Hello"}]


def test_create_with_a_recipe_sends_the_compiled_candidate_url4(
    default: list[httpx.Request],
) -> None:
    sf.chat.completions.create(model=fusion(), messages=[{"role": "user", "content": "Hi"}])
    sf.chat.completions.create("Hello", model=vote())

    chats = [r for r in default if r.url.path == CHAT_PATH]
    assert sent_body(chats[0])["model"] == compile_candidate(fusion()).url4
    assert sent_body(chats[1])["model"] == compile_candidate(vote(), operators=CATALOG).url4
    assert [r.url.path for r in default] == [CHAT_PATH, "/v1/operators", CHAT_PATH]


def test_stream_true_gives_a_chat_stream(default: list[httpx.Request]) -> None:
    with sf.chat.completions.create("Hello", model="openrouter/a", stream=True) as stream:
        assert isinstance(stream, ChatStream)
        text = "".join(chunk.text for chunk in stream)

    assert text == "Hello"


def test_model_is_a_required_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_default_client, "default_client", _no_default)

    with pytest.raises(TypeError, match="model"):
        cast(Any, sf.chat.completions).create("Hello")
    with pytest.raises(TypeError):
        cast(Any, sf.chat).endpoint()


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (lambda: sf.chat.completions.create("Hello", model=cast(Any, 42)), TypeError),
        (lambda: sf.chat.completions.create("Hello", model="  "), ValueError),
        (
            lambda: sf.chat.completions.create(
                "Hello", model="openrouter/a", messages=[{"role": "user", "content": "x"}]
            ),
            TypeError,
        ),
        (lambda: sf.chat.completions.create("Hello", model="openrouter/a", n=2), PlanningError),
        (lambda: sf.chat.completions.create("Hello", model="openrouter/a", tool=[]), TypeError),
        (lambda: sf.chat.endpoint(cast(Any, 42)), TypeError),
    ],
)
def test_argument_errors_make_no_default_client(
    monkeypatch: pytest.MonkeyPatch,
    call: Callable[[], object],
    error: type[Exception],
) -> None:
    monkeypatch.setattr(_default_client, "default_client", _no_default)

    with pytest.raises(error):
        call()


def test_endpoint_goes_to_the_default_client(default: list[httpx.Request]) -> None:
    endpoint = sf.chat.endpoint("openrouter/a")
    recipe_endpoint = sf.chat.endpoint(model())

    assert isinstance(endpoint, InferenceEndpoint)
    assert endpoint.base_url == f"{ENGINE_URL}/v1"
    assert endpoint.model == "openrouter/a"
    assert recipe_endpoint.model == CAND
    assert default == []


def test_each_call_takes_the_default_client_of_that_time(monkeypatch: pytest.MonkeyPatch) -> None:
    first_requests: list[httpx.Request] = []
    second_requests: list[httpx.Request] = []
    first = recording_client(catalogue_engine, first_requests)
    second = recording_client(catalogue_engine, second_requests)
    monkeypatch.setattr(_default_client, "_client", first)
    try:
        sf.chat.completions.create("one", model="openrouter/a")
        # WHY sf.close(): it closes the first client and forgets it, as the next call needs.
        sf.close()
        monkeypatch.setattr(_default_client, "_client", second)
        sf.chat.completions.create("two", model="openrouter/a")
    finally:
        second.close()

    assert len(first_requests) == 1
    assert len(second_requests) == 1


def test_the_warning_names_the_line_of_the_caller(default: list[httpx.Request]) -> None:
    with pytest.warns(IgnoredParameterWarning) as record:
        sf.chat.completions.create("Hello", model="openrouter/a", max_tokens=5)

    assert len(record) == 1
    # WHY __file__: the warning names the line of the caller, which is this file.
    assert record[0].filename == __file__


def _typed_rows(flag: bool) -> None:
    # AIDEV-NOTE: never called; pyright reads these rows against the overloads.
    assert_type(sf.chat.completions.create("hi", model="m"), ChatCompletion)
    assert_type(sf.chat.completions.create("hi", model="m", stream=True), ChatStream)
    assert_type(
        sf.chat.completions.create("hi", model="m", stream=flag), ChatCompletion | ChatStream
    )
    assert_type(sf.chat.endpoint("m"), InferenceEndpoint)
