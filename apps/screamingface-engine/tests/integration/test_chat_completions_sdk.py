"""POST /v1/chat/completions through the `openai` SDK, on the local in-process App (U4).

FEATURE: OpenAI-compatible Engine API, unit U4 (prd/chat-completion.md CC-22, CC-23, CC-29, CC-30,
CC-31). Plan decision D1: these are Engine integration tests. The App runs the real executor in
process, a fake gateway (an `httpx.MockTransport`) answers each model call, and the `openai` SDK
is the client. No replay lane, no network: each URL that could leave the machine uses `.invalid`.

STORY: as a developer with an OpenAI client, I point its base URL at the Engine and send a model id
or a URL4 recipe as `model`; I get a normal chat completion back.
"""

from __future__ import annotations

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
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.models.registry import encode_route_id
from url4 import RelExpr, expr, render, src, text

SECRET = "chat-completions-sdk-secret-000000000"
EMAIL = "dev@example.com"
GATEWAY = "http://aigateway.test"
MEMBER, SYNTH, COLON = "prov/a", "prov/b", "prov/c:free"
# WHY: GET /v1/models lists a gateway id in its route form, `:` written as `~` (C3, CC-S32).
LISTED = (MEMBER, SYNTH, "prov/c~free")
REPLIES = {MEMBER: "member answer", SYNTH: "Paris", COLON: "free answer"}
# A model step on a remote node: url4 refuses it before any I/O (peer/server.py remote guard).
REMOTE_RECIPE = "(model_1:0.0:url4://remote.invalid/v1($input)!'')!'$model_1'"


def _body(content: str) -> dict[str, Any]:
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
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
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


@dataclass
class _Gateway:
    """The fake gateway: one reply per model; it keeps each request body in call order."""

    seen: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.seen.append(sent)
        return httpx.Response(
            200, headers={"X-AIGW-Cache": "miss"}, json=_body(REPLIES[sent["model"]])
        )

    def messages_for(self, model: str) -> list[list[dict[str, Any]]]:
        return [sent["messages"] for sent in self.seen if sent["model"] == model]


class _ModelParameters:
    """The model-parameter source: 200 for each listed id (in either form), else not installed."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.seen.append(model)
        if model not in {*LISTED, COLON}:
            raise ModelNotInstalled(model)
        return ModelParameterResponse(status=200, content=b"{}")

    async def aclose(self) -> None:
        pass


class _Catalog:
    """The catalog behind GET /v1/models: the same fixed list for each caller."""

    async def fetch(self, credential: Credential) -> ModelCatalog:
        body: dict[str, object] = {
            "object": "list",
            "data": [{"id": model, "object": "model"} for model in LISTED],
        }
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
                ModelSpec(id=encode_route_id(model), web_search=False) for model in REPLIES
            ),
        )
    )


@dataclass
class _Stack:
    app: FastAPI
    http: TestClient
    gateway: _Gateway


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[_Stack]:
    """The local App over the real executor, a filesystem blob store and the fake gateway."""
    settings = Settings(
        jwt_secret=SECRET,
        blob_store="filesystem",
        blobs_dir=str(tmp_path / "blobs"),
        chat_max_wait_s=30.0,
    )
    gateway = _Gateway()
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


def _sdk(http: TestClient, *, identity: bool = True) -> openai.OpenAI:
    headers = {"X-User-Email": EMAIL} if identity else {}
    return openai.OpenAI(
        base_url="http://testserver/v1",
        api_key="unused",
        http_client=http,
        max_retries=0,
        default_headers=headers,
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


def test_local_stack_fusion_answers_openai_sdk_request(stack: _Stack) -> None:
    """CC-22 (CC-S5): a local caller with no identity runs a Fusion URL4 through the SDK."""
    stack.app.state.runs_require_identity = False
    recipe = _fusion_recipe()

    completion = _sdk(stack.http, identity=False).chat.completions.create(
        model=recipe, messages=[{"role": "user", "content": "Capital of France?"}]
    )

    assert completion.id.startswith("chatcmpl-")
    assert completion.object == "chat.completion"
    assert completion.model == recipe
    assert completion.choices[0].message.content == REPLIES[SYNTH]
    assert completion.choices[0].finish_reason == "stop"
    # INVARIANT: usage and cost are the sum over ALL 3 model calls of the ensemble (contracts C9),
    # not the final call alone: each fake reply is 10 + 4 tokens and 0.001 credits.
    assert len(stack.gateway.seen) == 3
    usage = completion.usage
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (30, 12, 42)
    extra = _extra(completion)
    assert extra["status"] == "answered"
    assert extra["cost_usd"] == "0.003"


def test_get_v1_models_is_unchanged(stack: _Stack) -> None:
    """CC-23 (CC-S32): the SDK lists the catalog as GET /v1/models does; each id is a `model`."""
    sdk = _sdk(stack.http)

    listed = [model.id for model in sdk.models.list()]
    direct = stack.http.get("/v1/models", headers={"X-User-Email": EMAIL})

    assert direct.status_code == 200
    assert listed == [row["id"] for row in direct.json()["data"]]
    assert listed == list(LISTED)

    # C3: a listed id in its route form (`~`) is a valid `model` value, not a 404.
    completion = sdk.chat.completions.create(
        model="prov/c~free", messages=[{"role": "user", "content": "Hi"}]
    )
    assert completion.choices[0].message.content == REPLIES[COLON]
    assert [sent["model"] for sent in stack.gateway.seen] == [COLON]


def test_multi_turn_text_and_developer_role_pass_as_native_messages(stack: _Stack) -> None:
    """CC-29 (CC-S30, D4): the model call gets the client messages as sent, no added system."""
    messages: list[Any] = [
        {"role": "system", "content": "Be brief."},
        {"role": "developer", "content": "Answer in French."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Bonjour"},
        {"role": "user", "content": "Capital of France?"},
    ]

    completion = _sdk(stack.http).chat.completions.create(model=MEMBER, messages=messages)

    assert completion.choices[0].message.content == REPLIES[MEMBER]
    assert stack.gateway.messages_for(MEMBER) == [messages]


def test_picture_parts_reach_model_steps_as_v2_parts(stack: _Stack) -> None:
    """CC-30 (CC-S31): a `data:` picture part reaches the model call unchanged."""
    picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    content: list[Any] = [{"type": "text", "text": "what is this?"}, picture]

    _sdk(stack.http).chat.completions.create(
        model=MEMBER, messages=[{"role": "user", "content": content}]
    )

    sent = stack.gateway.messages_for(MEMBER)
    assert len(sent) == 1
    users = [m for m in sent[0] if m["role"] == "user"]
    assert any(isinstance(m["content"], list) and picture in m["content"] for m in users)


def test_remote_node_in_model_is_refused_as_on_get_q(stack: _Stack) -> None:
    """CC-31 (CC-S33): a remote node in `model` fails as on GET /?q=, before any model call."""
    with pytest.raises(openai.APIStatusError) as caught:
        _sdk(stack.http).chat.completions.create(
            model=REMOTE_RECIPE, messages=[{"role": "user", "content": "Hi"}]
        )

    # WHY 502 internal_error: `x.remote_node_unsupported` is not a code the Engine vouches for,
    # so the terminal table gives its generic failed row (prd/chat-completion.md §3.2).
    assert caught.value.status_code == 502
    assert caught.value.response.json()["error"]["code"] == "internal_error"
    assert stack.gateway.seen == []

    token = stack.http.post("/token").json()["token"]
    on_get = stack.http.get(
        "/",
        params={"q": REMOTE_RECIPE},
        headers={"URL4-Capability": token, "X-User-Email": EMAIL},
    )

    assert on_get.status_code == 502
    assert on_get.json()["code"] == "internal_error"
    assert stack.gateway.seen == []
