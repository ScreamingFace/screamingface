"""The chat run sends what the Candidate route sends (chat-run PRD CR-S2, CR-S16; contracts C7).

FEATURE: chat-run. The turn route evaluates the recipe as built: the same request bytes, the same
Gate decisions and the same Budget records as a benchmark Case with the same input.
INVARIANT: the handler binds no retrieval policy, so each model step follows its route for web
search (the CR-S16 table).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from _chat_world import (
    Gateway,
    chat_store,
    chat_world,
    ingest_chat_input,
    run_candidate_route,
    run_turn,
)
from _gate_world import fixture

import screamingface_engine.world.chat_turn
from screamingface_engine.benchmarks.contract import (
    CandidateInvocation,
    decode_candidate_invocation_record,
)
from screamingface_engine.chat.input import CHAT_INPUT_SCHEMA, decode_chat_input
from screamingface_engine.chat.recipe import one_model_recipe
from screamingface_engine.chat.result import ChatResult
from screamingface_engine.chat.views import text_view
from screamingface_engine.chat.wire import canonical_json
from screamingface_engine.retrieval_policy import RetrievalPolicy, current_retrieval_policy
from screamingface_engine.world.chat_turn import install_chat_turn
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, build, expr, render, src, text
from url4.peer.server import Url4Node

MESSAGES = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "An integral please: what is 2 + 2?"},
]
_COMBINE_CONTRACT = Path(__file__).parent / "data" / "combine_contract"
_NATIVE = "openrouter/anthropic/claude-opus-4.8"
_TOOLS = "claude-opus-4-8"
_SEARCH_OFF = "?web_search=false&q="


def _input_text() -> str:
    """The text view of MESSAGES, the input both paths bind to `$input`."""
    value = {"schema": CHAT_INPUT_SCHEMA, "messages": MESSAGES}
    record = decode_chat_input(canonical_json(value))
    return text_view(record.messages, None)


async def _both_paths(
    recipe: str, replies: dict[str, str], *, web_search: bool = False
) -> tuple[ChatResult, Gateway, CandidateInvocation, Gateway]:
    """Run `recipe` once as a chat turn and once on the Candidate route, each on a fresh gateway."""
    chat_gateway, candidate_gateway = Gateway(replies), Gateway(replies)
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    async with chat_world(chat_gateway, web_search=web_search) as node:
        result = await run_turn(node, recipe, ref, reader)
    async with chat_world(candidate_gateway, web_search=web_search) as node:
        # WHY quoted: the case input is URL4 context, and a benchmark renders a text input as a
        # quoted literal, so the JSON text view reaches `$input` unchanged.
        candidate = await run_candidate_route(node, recipe, render(text(_input_text())))
    return result, chat_gateway, candidate, candidate_gateway


def _model_steps_search_off(recipe: str) -> str:
    """The SDK fusion with `web_search=false` on each model step, as a RelExpr param."""
    edited = recipe
    for route in ("member-a", "member-b", "member-c", "synth"):
        native = f"/openrouter/prov/{route}"
        edited = edited.replace(f"/prov/{route}(", f"{native}{_SEARCH_OFF}(", 1)
    return edited


# --- CR-7: the same request bytes ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_run_without_tools_sends_same_request_bytes_as_candidate_route() -> None:
    fusion = (_COMBINE_CONTRACT / "model_synthesizer_candidate.url4").read_text("utf-8")
    recipe = _model_steps_search_off(fusion.removesuffix("\n"))
    assert recipe.count("web_search=false") == 4
    assert build(recipe) is not None
    # WHY native routes that search by default: without the param, the chat path (no policy)
    # would ask the gateway to search and the bytes would differ.
    replies = {
        "openrouter/prov/member-a": "4",
        "openrouter/prov/member-b": "4",
        "openrouter/prov/member-c": "5",
        "openrouter/prov/synth": "The answer is 4.",
    }

    result, chat_gateway, candidate, candidate_gateway = await _both_paths(
        recipe, replies, web_search=True
    )

    assert len(chat_gateway.seen) == 4
    assert all("web_search" not in body and "tools" not in body for body in chat_gateway.seen)
    assert chat_gateway.seen == candidate_gateway.seen
    assert result.status == "answered"
    assert result.content == candidate.output == "The answer is 4."

    one = one_model_recipe("prov/a")
    result, chat_gateway, candidate, candidate_gateway = await _both_paths(one, {"prov/a": "4"})

    assert len(chat_gateway.seen) == 1
    assert chat_gateway.seen == candidate_gateway.seen
    assert result.content == candidate.output == "4"


# --- CR-8: a Gate recipe runs as built ----------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_run_runs_gate_recipe_and_skipped_branch_makes_zero_calls() -> None:
    replies = {"prov/math": "M", "prov/coder": "C", "prov/general": "G"}

    result, chat_gateway, candidate, candidate_gateway = await _both_paths(
        fixture("keyword_router.url4"), replies
    )

    assert [body["model"] for body in chat_gateway.seen] == ["prov/math"]
    assert chat_gateway.calls("prov/coder") == 0
    assert chat_gateway.calls("prov/general") == 0
    assert result.status == "answered"
    assert result.content == candidate.output == "M"
    assert chat_gateway.seen == candidate_gateway.seen


# --- CR-22: each step follows its route for web search -----------------------------------------


def _search_off(model_id: str) -> str:
    """A one-model recipe whose step sets `web_search=false`."""
    step = RelExpr(
        path=f"/{model_id}",
        context="$input",
        intent=text(""),
        params=(("web_search", "false"),),
    )
    return render(expr(src(step, name="model_1", weight=0.0), intent=text("$model_1")))


@asynccontextmanager
async def _search_world(
    gateway: Gateway, tavily_calls: list[httpx.Request], *, search_key: bool
) -> AsyncIterator[Url4Node]:
    """A gateway world with a native-search route and an Engine-tools route, and the turn route."""

    def tavily(request: httpx.Request) -> httpx.Response:
        tavily_calls.append(request)
        return httpx.Response(500, json={"error": "offline"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    tavily_client = httpx.AsyncClient(
        transport=httpx.MockTransport(tavily), base_url="https://tavily.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=_NATIVE, models=(ModelSpec(id=_NATIVE), ModelSpec(id=_TOOLS))
        ),
        client=client,
        tavily_api_key="tv-key" if search_key else None,
        tavily_client=tavily_client,
    )
    try:
        install_chat_turn(world.node)
        yield world.node
    finally:
        await world.aclose()
        await tavily_client.aclose()
        await client.aclose()


def _provider_searches(body: dict[str, Any]) -> None:
    assert body["web_search"] is True
    assert "tools" not in body
    assert "web_search_excluded_domains" not in body


def _engine_tools(body: dict[str, Any]) -> None:
    assert [tool["function"]["name"] for tool in body["tools"]] == ["web_search", "web_fetch"]
    assert "web_search" not in body


def _plain(body: dict[str, Any]) -> None:
    assert "tools" not in body
    assert "web_search" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("recipe", "search_key", "check"),
    [
        pytest.param(one_model_recipe(_NATIVE), True, _provider_searches, id="provider-searches"),
        pytest.param(one_model_recipe(_TOOLS), True, _engine_tools, id="engine-tools-with-key"),
        pytest.param(one_model_recipe(_TOOLS), False, _plain, id="engine-tools-without-key"),
        pytest.param(_search_off(_NATIVE), True, _plain, id="recipe-false"),
    ],
)
async def test_step_follows_its_route_for_web_search_in_each_of_four_cases(
    recipe: str, search_key: bool, check: Callable[[dict[str, Any]], None]
) -> None:
    policies: list[RetrievalPolicy | None] = []

    def reply(_: dict[str, Any]) -> str:
        policies.append(current_retrieval_policy())
        return "Paris"

    gateway = Gateway({_NATIVE: reply, _TOOLS: reply})
    tavily_calls: list[httpx.Request] = []
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)

    async with _search_world(gateway, tavily_calls, search_key=search_key) as node:
        result = await run_turn(node, recipe, ref, reader)

    assert result.status == "answered"
    assert result.content == "Paris"
    assert len(gateway.seen) == 1
    check(gateway.seen[0])
    assert policies == [None]
    assert tavily_calls == []


# --- CR-28: the same Budget, Gate and reducer records ------------------------------------------


@pytest.mark.asyncio
async def test_budget_gate_and_cost_reducer_give_same_records_as_candidate_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelopes: list[str] = []
    real = screamingface_engine.world.chat_turn.evaluate_candidate_recipe

    async def recording(*args: Any, **kwargs: Any) -> str:
        envelope = await real(*args, **kwargs)
        envelopes.append(envelope)
        return envelope

    monkeypatch.setattr(
        screamingface_engine.world.chat_turn, "evaluate_candidate_recipe", recording
    )
    replies = {"prov/alpha": "A", "prov/beta": "B", "prov/gamma": "C", "prov/large": "L"}

    result, chat_gateway, candidate, candidate_gateway = await _both_paths(
        fixture("d9_budget_cap.url4"), replies
    )

    (envelope,) = envelopes
    chat = decode_candidate_invocation_record(envelope)
    assert chat.operations is not None
    assert candidate.operations is not None
    assert [op.model_dump() for op in chat.operations] == [
        op.model_dump() for op in candidate.operations
    ]
    assert (chat.status, chat.output, chat.abstained) == (
        candidate.status,
        candidate.output,
        candidate.abstained,
    )
    assert chat.output == "L"
    assert result.content == "L"
    decision = next(op.decision for op in chat.operations if op.operation_id == "op_gate_1")
    assert decision is not None
    budget = json.loads(decision.model_dump_json())["budget"]
    assert budget and budget[0]["cap"] == 0.05
    assert any(op.charges for op in chat.operations)
    assert any(op.combine is not None for op in chat.operations)
    assert chat_gateway.seen == candidate_gateway.seen
