"""The local chat stack of the `openai` SDK tests: the App, the real executor, a fake gateway.

FEATURE: OpenAI-compatible Engine API, units U4 and U7 (prd/chat-completion.md CC-22, prd/docs.md
DOC-1). Plan decision D1: the App runs the real executor in process, a fake gateway (an
`httpx.MockTransport`) answers each model call, and a test drives the App with the `openai` SDK.
No request leaves the machine.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
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

GATEWAY = "http://aigateway.test"


def gateway_body(content: str) -> dict[str, Any]:
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
class FakeGateway:
    """The fake gateway: one reply per model; it keeps each request body in call order."""

    replies: Mapping[str, str]
    seen: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.seen.append(sent)
        return httpx.Response(
            200, headers={"X-AIGW-Cache": "miss"}, json=gateway_body(self.replies[sent["model"]])
        )

    def messages_for(self, model: str) -> list[list[dict[str, Any]]]:
        return [sent["messages"] for sent in self.seen if sent["model"] == model]


class FakeModelParameters:
    """The model-parameter source: 200 for each known id, else not installed."""

    def __init__(self, known: Collection[str]) -> None:
        self._known = frozenset(known)
        self.seen: list[str] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.seen.append(model)
        if model not in self._known:
            raise ModelNotInstalled(model)
        return ModelParameterResponse(status=200, content=b"{}")

    async def aclose(self) -> None:
        pass


class FakeCatalog:
    """The catalog behind GET /v1/models: the same fixed list for each caller."""

    def __init__(self, listed: Sequence[str]) -> None:
        self._listed = tuple(listed)

    async def fetch(self, credential: Credential) -> ModelCatalog:
        body: dict[str, object] = {
            "object": "list",
            "data": [{"id": model, "object": "model"} for model in self._listed],
        }
        return ModelCatalog(body=body, etag=compute_etag(body))

    def max_age_s(self, credential: Credential) -> int:
        return 60


def chat_world(models: Sequence[str], default_model: str) -> WorldConfig:
    """A world with one route per gateway model id, each with web search off."""
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url=GATEWAY,
            default_model=default_model,
            # WHY encode_route_id: a ModelSpec id is always the route form (world/config.py _merge).
            models=tuple(
                ModelSpec(id=encode_route_id(model), web_search=False) for model in models
            ),
        )
    )


@dataclass
class ChatStack:
    app: FastAPI
    http: TestClient
    gateway: FakeGateway


@contextmanager
def chat_stack(
    tmp_path: Path,
    *,
    secret: str,
    replies: Mapping[str, str],
    listed: Sequence[str],
    known: Collection[str],
    default_model: str,
) -> Iterator[ChatStack]:
    """The local App over the real executor, a filesystem blob store and the fake gateway.

    `replies` gives the gateway reply of each model id; the world has one route for each of them.
    `listed` is the catalogue of GET /v1/models; `known` are the ids that the model-parameters
    lookup knows.
    """
    settings = Settings(
        jwt_secret=secret,
        blob_store="filesystem",
        blobs_dir=str(tmp_path / "blobs"),
        chat_max_wait_s=30.0,
    )
    gateway = FakeGateway(replies)
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway.handle), base_url=GATEWAY)
    stream = InMemoryEventStream()
    world = chat_world(tuple(replies), default_model)
    runner = InProcessJobRunner(
        stream,
        lambda env: build_executor(env, world, client=client),
        base_env=blob_store_values(settings),
    )
    app = create_app(
        settings,
        stream=stream,
        job_runner=runner,
        catalog=FakeCatalog(listed),
        model_parameters=FakeModelParameters(known),
    )
    app.router.on_shutdown.append(runner.aclose)
    app.router.on_shutdown.append(client.aclose)
    with TestClient(app) as http:
        yield ChatStack(app, http, gateway)
