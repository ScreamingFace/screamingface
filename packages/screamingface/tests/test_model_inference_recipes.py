"""MI-7, MI-9, MI-10 and MI-30 through InferenceClient (contracts C1.1, C3; P2, P14, P17)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from _chat_engine import (
    BENCH_ROUTE,
    CAND,
    CATALOG,
    CHAT_PATH,
    EVAL,
    NOT_TEXT,
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

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.errors import PlanningError
from screamingface.inference import InferenceClient
from screamingface.recipe import Recipe

BUILDERS: list[Callable[[], Recipe]] = [model, fusion, pipeline, vote, gate, cascade]
CORRECTIVE: list[Callable[[], Recipe]] = [self_corrective, corrective_loop]


@pytest.mark.parametrize(
    ("recipe", "has_reducer"),
    [
        pytest.param(model, False, id="model"),
        pytest.param(fusion, False, id="fusion"),
        pytest.param(pipeline, False, id="pipeline"),
        pytest.param(vote, True, id="vote"),
        pytest.param(gate, True, id="gate"),
        pytest.param(cascade, True, id="cascade"),
    ],
)
def test_complete_sends_the_compiled_candidate_text(
    recipe: Callable[[], Recipe], has_reducer: bool
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        InferenceClient(recipe(), client=client).chat.completions.create("Hello")

    expected = (
        compile_candidate(recipe(), operators=CATALOG).url4
        if has_reducer
        else compile_candidate(recipe()).url4
    )
    [chat] = [request for request in requests if request.url.path == CHAT_PATH]
    assert sent_body(chat)["model"] == expected


@pytest.mark.parametrize("recipe", BUILDERS, ids=[build.__name__ for build in BUILDERS])
def test_constructor_uses_no_network(recipe: Callable[[], Recipe]) -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        InferenceClient(recipe(), client=client)

    assert requests == []


def test_reducer_recipe_loads_the_catalogue_once_at_first_call() -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        llm = InferenceClient(vote(), client=client)
        llm.chat.completions.create("one")
        llm.chat.completions.create("two")

    assert [request.url.path for request in requests] == ["/v1/operators", CHAT_PATH, CHAT_PATH]


def test_recipe_without_a_reducer_never_loads_the_catalogue() -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        llm = InferenceClient(fusion(), client=client)
        llm.chat.completions.create("one")
        llm.chat.completions.create("two")

    assert [request.url.path for request in requests] == [CHAT_PATH, CHAT_PATH]


@pytest.mark.parametrize("recipe", CORRECTIVE, ids=[build.__name__ for build in CORRECTIVE])
def test_corrective_loop_is_recipe_not_supported_from_the_constructor(
    recipe: Callable[[], Recipe],
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        with pytest.raises(PlanningError) as raised:
            InferenceClient(recipe(), client=client)

    assert raised.value.code == "recipe_not_supported"
    assert requests == []


def test_complete_raises_the_compiler_error_before_the_chat_request() -> None:
    requests: list[httpx.Request] = []
    with recording_client(catalogue_engine, requests) as client:
        llm = InferenceClient(
            sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote(over="benchmark"), client=client
        )
        with pytest.raises(ValueError, match="over='benchmark' needs a benchmark"):
            llm.chat.completions.create("Hello")

    assert [request.url.path for request in requests] == ["/v1/operators"]


def test_complete_sends_a_candidate_binding_that_is_not_text_unchanged() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        InferenceClient(NOT_TEXT, client=client).chat.completions.create("Hello")

    assert sent_body(requests[0])["model"] == NOT_TEXT


def test_complete_sends_the_candidate_source_of_an_evaluation_url4() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        InferenceClient(sf.Url4(EVAL), client=client).chat.completions.create("Hello")

    assert sent_body(requests[0])["model"] == CAND


@pytest.mark.parametrize("text", [BENCH_ROUTE])
def test_constructor_refuses_an_evaluation_url4_with_no_candidate(text: str) -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        with pytest.raises(PlanningError) as raised:
            InferenceClient(text, client=client)

    assert raised.value.code == "recipe_invalid"
    assert requests == []
