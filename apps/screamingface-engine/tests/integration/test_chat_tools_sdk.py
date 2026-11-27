"""A two-turn tool loop on POST /v1/chat/completions via the `openai` SDK, plain and streamed (U6).

FEATURE: OpenAI-compatible Engine API, unit U6 (prd/tool-calls.md TC-21, TC-S1, TC-S2, TC-S3;
prd/streaming.md ST-10, ST-S2, ST-S10). Plan decision D1: these are Engine integration tests.
The App runs the real executor in process, a fake gateway (an `httpx.MockTransport`) answers each
model call, and the `openai` SDK is the client. No replay lane, no network: each URL that could
leave the machine uses `.invalid` or the fake gateway base URL.

STORY: as a developer with an agent loop, I send tools with a Fusion recipe as `model`; the
synthesizer asks for a tool, I run it and send the result back, and the next turn answers in text.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.app import blob_store_values, create_app
from screamingface_engine.catalog.port import (
    Credential,
    ModelCatalog,
    ModelNotInstalled,
    ModelParameterResponse,
    compute_etag,
)
from screamingface_engine.config import Settings
from screamingface_engine.rest import chat_body
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.models.registry import encode_route_id
from url4 import RelExpr, expr, render, src, text

SECRET = "chat-tools-sdk-secret-000000000000000"
EMAIL = "dev@example.com"
HEADERS = {"X-User-Email": EMAIL}
GATEWAY = "http://aigateway.test"
MEMBER, SYNTH = "prov/a", "prov/b"
MODELS = (MEMBER, SYNTH)
MEMBER_REPLY = "member answer"
FINAL_REPLY = "It is sunny in Paris."
ARGUMENTS = '{"city":"Paris"}'
TOOL_RESULT = "sunny, 21 C"
# WHY Any: the SDK types its parameters as TypedDicts, and a plain dict is the client wire form.
TOOL: Any = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "The weather in a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
TOOL_CALL: dict[str, Any] = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "get_weather", "arguments": ARGUMENTS},
}
QUESTION: Any = {"role": "user", "content": "Weather in Paris?"}
KEEP_ALIVE = ": keep-alive"


def _body(message: dict[str, Any], finish_reason: str) -> dict[str, Any]:
    """A gateway chat completion that the connector prices: 10 + 4 tokens, 0.001 credits."""
    cost = {"status": "reported", "amount": "0.001", "unit": "openrouter_credits", "source": "x"}
    attempt = {
        "outcome": "succeeded",
        "provider": "openrouter",
        "response_model": "m",
        "latency_ms": 30,
        "usage": {"input": {"total": 10}, "output": {"total": 4}},
        "direct_cost": cost,
    }
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "complete",
                "omitted_attempts": 0,
                "attempts": [attempt],
                "cache": {"status": "miss", "reference": None},
            },
            "request_economics": {
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [{"unit": "openrouter_credits", "amount": "0.001"}],
            },
        },
    }


def _synth_reply(sent: dict[str, Any]) -> dict[str, Any]:
    """A tool call while no tool result is in the request, else the text answer."""
    if any(m.get("role") == "tool" for m in sent["messages"]):
        return _body({"role": "assistant", "content": FINAL_REPLY}, "stop")
    message = {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]}
    return _body(message, "tool_calls")


@dataclass
class _Gateway:
    """The fake gateway: it keeps each request body in call order; SYNTH can answer late."""

    synth_delay_s: float = 0.0
    seen: list[dict[str, Any]] = field(default_factory=list)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.seen.append(sent)
        if sent["model"] == SYNTH:
            await asyncio.sleep(self.synth_delay_s)
            reply = _synth_reply(sent)
        else:
            reply = _body({"role": "assistant", "content": MEMBER_REPLY}, "stop")
        return httpx.Response(200, headers={"X-AIGW-Cache": "miss"}, json=reply)

    def bodies_for(self, model: str) -> list[dict[str, Any]]:
        return [sent for sent in self.seen if sent["model"] == model]


class _ModelParameters:
    """The model-parameter source: 200 for each declared model, else not installed."""

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        if model not in MODELS:
            raise ModelNotInstalled(model)
        return ModelParameterResponse(status=200, content=b"{}")

    async def aclose(self) -> None:
        pass


class _Catalog:
    """The catalog behind GET /v1/models: both models list `tools` (TC-S10)."""

    async def fetch(self, credential: Credential) -> ModelCatalog:
        rows = [
            {"id": model, "object": "model", "supported_parameters": ["tools", "temperature"]}
            for model in MODELS
        ]
        body: dict[str, object] = {"object": "list", "data": rows}
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        return 60


def _world() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url=GATEWAY,
            default_model=MEMBER,
            # WHY encode_route_id: a ModelSpec id is always the route form (world/config.py _merge).
            models=tuple(
                ModelSpec(id=encode_route_id(model), web_search=False) for model in MODELS
            ),
        )
    )


@dataclass
class _Stack:
    app: FastAPI
    http: TestClient
    gateway: _Gateway


def _stack(tmp_path: Path, gateway: _Gateway, *, keepalive_s: float) -> Iterator[_Stack]:
    """The local App over the real executor, a filesystem blob store and the fake gateway."""
    settings = Settings(
        jwt_secret=SECRET,
        blob_store="filesystem",
        blobs_dir=str(tmp_path / "blobs"),
        chat_max_wait_s=30.0,
        chat_keepalive_s=keepalive_s,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway.handle), base_url=GATEWAY)
    stream = InMemoryEventStream()
    world = _world()
    runner = InProcessJobRunner(
        stream,
        lambda env: build_executor(env, world, client=client),
        base_env=blob_store_values(settings),
    )
    app = create_app(
        settings,
        stream=stream,
        job_runner=runner,
        catalog=_Catalog(),
        model_parameters=_ModelParameters(),
    )
    app.router.on_shutdown.append(runner.aclose)
    app.router.on_shutdown.append(client.aclose)
    with TestClient(app) as http:
        yield _Stack(app, http, gateway)


@pytest.fixture(autouse=True)
def tools_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the fixed tool refusal of the chat route for the tests of this module.

    WHY: tool calls are turned off at the boundary (rest/chat_body.py::_tool_use, owner decision
    of 2026-11-24). The tool loop behind the check stays, and these tests keep it correct. This
    is a test seam only; no setting removes the check in a deployment.
    """
    monkeypatch.setattr(chat_body, "_tool_use", lambda request: None)


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[_Stack]:
    """The stack with a gateway that answers at once."""
    yield from _stack(tmp_path, _Gateway(), keepalive_s=15.0)


@pytest.fixture
def slow_stack(tmp_path: Path) -> Iterator[_Stack]:
    """The stack with a late synthesizer (0.3 s) and a 0.05 s keep-alive, for streams."""
    yield from _stack(tmp_path, _Gateway(synth_delay_s=0.3), keepalive_s=0.05)


def _sdk(http: TestClient) -> openai.OpenAI:
    return openai.OpenAI(
        base_url="http://testserver/v1",
        api_key="unused",
        http_client=http,
        max_retries=0,
        default_headers=HEADERS,
    )


def _fusion_recipe() -> str:
    """Two members on one route, then synthesis_1 on another route over both."""

    def member(name: str, answer: str) -> Any:
        return src(
            RelExpr(path="/" + MEMBER, context="$input", intent=text(answer)), name=name, weight=0.0
        )

    synthesis = src(
        RelExpr(path="/" + SYNTH, context="$model_1 $model_2", intent=text("Merge")),
        name="synthesis_1",
        weight=0.0,
    )
    return render(
        expr(
            member("model_1", "Answer A"),
            member("model_2", "Answer B"),
            synthesis,
            intent=text("$synthesis_1"),
        )
    )


def _extra(completion: Any) -> dict[str, Any]:
    extra = completion.model_extra or {}
    value = extra.get("screamingface")
    assert isinstance(value, dict), "the response has no screamingface field"
    return value


def _second_turn(content: str | None) -> list[Any]:
    """The client side of the loop: the assistant tool call and the tool result appended."""
    assistant = {"role": "assistant", "content": content, "tool_calls": [TOOL_CALL]}
    tool = {"role": "tool", "tool_call_id": "call_1", "content": TOOL_RESULT}
    return [QUESTION, assistant, tool]


def _text_of(body: dict[str, Any], role: str) -> str:
    """All text of the messages with `role` in one gateway request, joined."""
    parts: list[str] = []
    for message in body["messages"]:
        if message.get("role") != role:
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return "\n".join(parts)


def _assert_members_see_no_tools(gateway: _Gateway) -> None:
    """TC-S2: a member step runs on the existing endpoint, with the text view and no tools."""
    for body in gateway.bodies_for(MEMBER):
        assert "tools" not in body
        assert "tool_choice" not in body


def _assert_synth_body(body: dict[str, Any]) -> None:
    """C8 (ans:Q14): the final step sends the client tools and no tool_choice."""
    assert body["tools"] == [TOOL]
    assert "tool_choice" not in body
    assert "parallel_tool_calls" not in body


def _assert_tool_call_answer(completion: Any) -> None:
    """TC-S1: the tool call of the synthesizer, unchanged, with finish_reason tool_calls."""
    choice = completion.choices[0]
    assert choice.finish_reason == "tool_calls"
    calls = choice.message.tool_calls
    assert calls is not None and len(calls) == 1
    call = calls[0]
    assert (call.id, call.type) == ("call_1", "function")
    assert (call.function.name, call.function.arguments) == ("get_weather", ARGUMENTS)
    # P13 of the SDK model inference spec: a tool-call reply with no text has content null.
    assert choice.message.content is None
    assert _extra(completion)["final_step"]["binding"] == "synthesis_1"


def _assert_second_turn_bodies(turn_two: list[dict[str, Any]]) -> None:
    """TC-S3: the members see the tool round as text, the final step sees it natively."""
    members = [body for body in turn_two if body["model"] == MEMBER]
    assert len(members) == 2
    for body in members:
        # TC-S3, §3.4 rules 2 and 3: a non-final step sees the tool call as a line of the
        # assistant text and the tool result as a user line.
        assert "[tool_call id=call_1 name=get_weather]" in _text_of(body, "assistant")
        assert f"[tool_result id=call_1] {TOOL_RESULT}" in _text_of(body, "user")
    synths = [body for body in turn_two if body["model"] == SYNTH]
    assert len(synths) == 1
    _assert_synth_body(synths[0])
    # §3.5: the final step gets the assistant tool call and the tool result as the client sent.
    sent = synths[0]["messages"]
    assert any(m.get("role") == "assistant" and m.get("tool_calls") == [TOOL_CALL] for m in sent)
    tools_sent = [m for m in sent if m.get("role") == "tool"]
    assert tools_sent == [{"role": "tool", "tool_call_id": "call_1", "content": TOOL_RESULT}]


def test_agent_two_turn_tool_loop_on_local_stack(stack: _Stack) -> None:
    """TC-21 (TC-S1, TC-S2, TC-S3): a tool call, then the tool result, then a text answer."""
    sdk = _sdk(stack.http)
    recipe = _fusion_recipe()
    gateway = stack.gateway

    first = sdk.chat.completions.create(model=recipe, messages=[QUESTION], tools=[TOOL])

    _assert_tool_call_answer(first)
    assert len(gateway.bodies_for(MEMBER)) == 2
    synth_first = gateway.bodies_for(SYNTH)
    assert len(synth_first) == 1
    _assert_synth_body(synth_first[0])
    _assert_members_see_no_tools(gateway)

    turn_count = len(gateway.seen)
    messages = _second_turn(first.choices[0].message.content)
    second = sdk.chat.completions.create(model=recipe, messages=messages, tools=[TOOL])

    assert second.choices[0].message.content == FINAL_REPLY
    assert second.choices[0].finish_reason == "stop"
    assert _extra(second)["final_step"]["binding"] == "synthesis_1"
    _assert_members_see_no_tools(gateway)
    _assert_second_turn_bodies(gateway.seen[turn_count:])


def _request(messages: list[Any]) -> dict[str, Any]:
    return {"model": _fusion_recipe(), "messages": messages, "tools": [TOOL], "stream": True}


def _assert_tool_call_chunks(chunks: list[Any]) -> None:
    """ST-S2: one chunk holds the whole tool call; the last choice chunk ends with tool_calls."""
    with_calls = [c for c in chunks if c.choices and c.choices[0].delta.tool_calls]
    assert len(with_calls) == 1
    deltas = with_calls[0].choices[0].delta.tool_calls
    assert deltas is not None and len(deltas) == 1
    delta = deltas[0]
    assert (delta.index, delta.id, delta.type) == (0, "call_1", "function")
    assert delta.function is not None
    assert (delta.function.name, delta.function.arguments) == ("get_weather", ARGUMENTS)
    with_choices = [c for c in chunks if c.choices]
    assert with_choices[-1].choices[0].finish_reason == "tool_calls"


def _raw_lines(stack: _Stack) -> list[str]:
    """The non-empty lines of one streamed turn-1 request, read raw."""
    with stack.http.stream(
        "POST", "/v1/chat/completions", json=_request([QUESTION]), headers=HEADERS
    ) as resp:
        assert resp.status_code == 200
        return [line for line in resp.iter_lines() if line]


def test_agent_stream_on_local_stack_with_tool_call(slow_stack: _Stack) -> None:
    """ST-10 (ST-S2, ST-S10): the tool call and the text answer, streamed through the SDK."""
    sdk = _sdk(slow_stack.http)
    recipe = _fusion_recipe()

    chunks = list(
        sdk.chat.completions.create(model=recipe, messages=[QUESTION], tools=[TOOL], stream=True)
    )

    _assert_tool_call_chunks(chunks)

    second = list(
        sdk.chat.completions.create(
            model=recipe, messages=_second_turn(None), tools=[TOOL], stream=True
        )
    )

    with_choices = [c for c in second if c.choices]
    assert "".join(c.choices[0].delta.content or "" for c in with_choices) == FINAL_REPLY
    assert with_choices[-1].choices[0].finish_reason == "stop"

    lines = _raw_lines(slow_stack)
    data_at = [i for i, line in enumerate(lines) if line.startswith("data:")]
    assert data_at, "the stream sent no data line"
    first_data = data_at[0]
    assert KEEP_ALIVE in lines[:first_data], "no keep-alive came before the first data line"
    # ST-S10: no comment line after the first data chunk.
    assert not any(line.startswith(":") for line in lines[first_data:])
    assert lines[data_at[-1]] == "data: [DONE]"
