"""MI-36: recipe.chat on each recipe kind (contracts C1.1, C1.2, C1.5; overview D14).

STORY: as an SDK user, I call my ensemble as a chat model with recipe.chat.completions.create(...)
and I make no new object.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from typing import Any, cast

import httpx
import pytest
from _chat_engine import (
    CAND,
    CATALOG,
    CHAT_PATH,
    ENGINE_URL,
    cascade,
    catalogue_engine,
    corrective_loop,
    fusion,
    gate,
    model,
    ok,
    pipeline,
    recording_client,
    self_corrective,
    sent_body,
    vote,
)
from _chat_stream import async_recording_client

import screamingface as sf
from screamingface import _default_client
from screamingface._evaluation.candidate import compile_candidate
from screamingface.chat_completion import ChatCompletion, ChatStream
from screamingface.errors import PlanningError
from screamingface.inference import InferenceEndpoint, RecipeChat, RecipeCompletions
from screamingface.recipe import Recipe
from screamingface.warnings import IgnoredParameterWarning


def sf_fusion() -> Recipe:
    return sf.Fusion(["openrouter/a", "openrouter/b"], synthesizer="openrouter/c")


def with_budget() -> Recipe:
    return sf.WithBudget(sf.Model("openrouter/a"), budget_usd=0.05)


ALL: list[Callable[[], Recipe]] = [
    model,
    fusion,
    sf_fusion,
    pipeline,
    vote,
    gate,
    cascade,
    with_budget,
    self_corrective,
    corrective_loop,
]


@pytest.fixture
def default(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    """The default client is a recording client on the catalogue Engine; yields its requests."""

    requests: list[httpx.Request] = []
    client = recording_client(catalogue_engine, requests)
    monkeypatch.setattr(_default_client, "_client", client)
    yield requests
    if not client.closed:
        client.close()


def _chat(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in requests if r.url.path == CHAT_PATH]


@pytest.mark.parametrize("recipe", ALL, ids=[build.__name__ for build in ALL])
def test_each_recipe_kind_has_chat(recipe: Callable[[], Recipe]) -> None:
    value = recipe()

    assert isinstance(value.chat, RecipeChat)
    assert isinstance(value.chat.completions, RecipeCompletions)


def test_the_access_sends_no_request_and_gives_a_new_object(default: list[httpx.Request]) -> None:
    for build in ALL:
        value = build()

        first = value.chat
        second = value.chat
        # WHY: recipes are frozen with slots and no hash, so the access never caches on them.
        assert first is not second
        _ = first.completions

    assert default == []


@pytest.mark.parametrize(
    ("recipe", "has_reducer"),
    [
        (model, False),
        (fusion, False),
        (sf_fusion, False),
        (pipeline, False),
        (with_budget, False),
        (vote, True),
        (gate, True),
        (cascade, True),
    ],
    ids=["model", "fusion", "sf_fusion", "pipeline", "with_budget", "vote", "gate", "cascade"],
)
def test_a_call_sends_the_compiled_candidate_url4_through_the_default_client(
    default: list[httpx.Request], recipe: Callable[[], Recipe], has_reducer: bool
) -> None:
    reply = recipe().chat.completions.create("Hello")

    expected = (
        compile_candidate(recipe(), operators=CATALOG).url4
        if has_reducer
        else compile_candidate(recipe()).url4
    )
    assert isinstance(reply, ChatCompletion)
    assert reply.text == "Hello"
    [chat] = _chat(default)
    assert sent_body(chat)["model"] == expected
    assert sent_body(chat)["messages"] == [{"role": "user", "content": "Hello"}]


def test_each_call_takes_the_default_client_of_that_time(monkeypatch: pytest.MonkeyPatch) -> None:
    first_requests: list[httpx.Request] = []
    second_requests: list[httpx.Request] = []
    first = recording_client(ok, first_requests)
    second = recording_client(ok, second_requests)
    monkeypatch.setattr(_default_client, "_client", first)
    chat = model().chat
    try:
        chat.completions.create("one")
        # WHY sf.close(): it closes the first client and forgets it.
        sf.close()
        monkeypatch.setattr(_default_client, "_client", second)
        chat.completions.create("two")
    finally:
        second.close()

    assert len(first_requests) == 1
    assert len(second_requests) == 1


def test_sf_configure_is_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_default_client, "_client", None)
    chat = model().chat
    try:
        sf.configure(engine_url="http://engine1.test", scoreboard_url="http://scoreboard1.test")
        # WHY: an http Engine needs no sign-in, and sf.Model has no reducer, so endpoint()
        # sends no request.
        first = chat.endpoint()
        sf.configure(engine_url="http://engine2.test", scoreboard_url="http://scoreboard2.test")
        second = chat.endpoint()
    finally:
        sf.close()

    assert first.base_url == "http://engine1.test/v1"
    assert second.base_url == "http://engine2.test/v1"
    assert first.model == second.model == CAND


def test_stream_true_gives_a_chat_stream(default: list[httpx.Request]) -> None:
    with model().chat.completions.create("Hello", stream=True) as stream:
        assert isinstance(stream, ChatStream)
        chunks = list(stream)

    assert "".join(chunk.text for chunk in chunks) == "Hello"
    [chat] = _chat(default)
    assert sent_body(chat)["stream"] is True


def test_endpoint_gives_the_candidate_url4_with_no_request(default: list[httpx.Request]) -> None:
    endpoint = model().chat.endpoint()

    assert isinstance(endpoint, InferenceEndpoint)
    assert endpoint.model == CAND
    assert endpoint.base_url == f"{ENGINE_URL}/v1"
    assert dict(endpoint.headers) == {}
    assert default == []


def test_endpoint_of_a_reducer_recipe_loads_the_catalogue(default: list[httpx.Request]) -> None:
    endpoint = vote().chat.endpoint()

    assert endpoint.model == compile_candidate(vote(), operators=CATALOG).url4
    assert [r.url.path for r in default] == ["/v1/operators"]


def test_the_warning_names_the_line_of_the_caller_for_recipe_chat(
    default: list[httpx.Request],
) -> None:
    with pytest.warns(IgnoredParameterWarning) as record:
        expected_line = sys._getframe().f_lineno + 1
        model().chat.completions.create("Hello", temperature=0.2)

    assert len(record) == 1
    # WHY __file__: the warning names the line of the caller, which is this file.
    assert record[0].filename == __file__
    assert record[0].lineno == expected_line
    assert "temperature" in str(record[0].message)
    [chat] = _chat(default)
    assert "temperature" not in sent_body(chat)


def test_the_warning_names_the_line_of_the_caller_for_sf_chat(
    default: list[httpx.Request],
) -> None:
    with pytest.warns(IgnoredParameterWarning) as record:
        expected_line = sys._getframe().f_lineno + 1
        sf.chat.completions.create("Hello", model="openrouter/a", temperature=0.2)

    assert len(record) == 1
    # WHY __file__: the warning names the line of the caller, which is this file.
    assert record[0].filename == __file__
    assert record[0].lineno == expected_line
    assert "temperature" in str(record[0].message)
    [chat] = _chat(default)
    assert "temperature" not in sent_body(chat)


def test_the_warning_names_the_line_of_the_caller_for_client_chat(
    default: list[httpx.Request],
) -> None:
    client = _default_client.default_client()

    with pytest.warns(IgnoredParameterWarning) as record:
        expected_line = sys._getframe().f_lineno + 1
        client.chat.completions.create("Hello", model="openrouter/a", temperature=0.2)

    assert len(record) == 1
    # WHY __file__: the warning names the line of the caller, which is this file.
    assert record[0].filename == __file__
    assert record[0].lineno == expected_line
    assert "temperature" in str(record[0].message)
    [chat] = _chat(default)
    assert "temperature" not in sent_body(chat)


@pytest.mark.asyncio
async def test_the_warning_names_the_line_of_the_caller_on_an_async_client() -> None:
    requests: list[httpx.Request] = []

    async with async_recording_client(ok, requests) as aclient:
        with pytest.warns(IgnoredParameterWarning) as record:
            expected_line = sys._getframe().f_lineno + 1
            reply = await aclient.chat.completions.create(
                "Hello", model="openrouter/a", temperature=0.2
            )

    assert reply.text == "Hello"
    assert len(record) == 1
    assert record[0].filename == __file__
    assert record[0].lineno == expected_line


@pytest.mark.parametrize(
    "recipe", [self_corrective, corrective_loop], ids=["self_corrective", "corrective_loop"]
)
def test_a_corrective_loop_is_refused_by_create_and_endpoint(
    default: list[httpx.Request], recipe: Callable[[], Recipe]
) -> None:
    # WHY: the property exists; the access raises nothing, and the call refuses.
    chat = recipe().chat

    with pytest.raises(PlanningError) as raised:
        chat.completions.create("Hello")
    assert raised.value.code == "recipe_not_supported"

    with pytest.raises(PlanningError) as raised_endpoint:
        chat.endpoint()
    assert raised_endpoint.value.code == "recipe_not_supported"
    assert default == []


def test_a_lone_step_and_a_url4_have_no_chat() -> None:
    assert not hasattr(sf.Fanout(["prov/a", "prov/b"]), "chat")
    assert not hasattr(sf.Synthesize("openrouter/c"), "chat")
    assert not hasattr(sf.Url4(CAND), "chat")


def test_recipe_create_has_no_model_parameter(default: list[httpx.Request]) -> None:
    # WHY cast(Any): the recipe create has no model parameter, so pyright refuses the keyword.
    completions = cast(Any, model().chat.completions)
    with pytest.raises(TypeError, match="unexpected keyword argument 'model'"):
        completions.create("Hello", model="openrouter/b")

    assert default == []


def test_an_argument_error_makes_no_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_default() -> sf.Client:
        raise AssertionError("the call made the default client")

    monkeypatch.setattr(_default_client, "_client", None)
    monkeypatch.setattr(_default_client, "default_client", no_default)
    chat = model().chat

    with pytest.raises(TypeError):
        chat.completions.create()
    with pytest.raises(ValueError):
        chat.completions.create("Hello", timeout=0)
    with pytest.raises(TypeError):
        chat.completions.create("Hello", tool=[])
