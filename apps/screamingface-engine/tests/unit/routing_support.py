"""Shared fixtures for the `/route-answer` tests (OME-1822): one world, one fake Gateway.

The world declares one public chat route, three private branch routes and one routing profile
over them. The fake Gateway answers the four metadata reads, the classification and the chat
calls from defaults or from a per-(path, model) script, and records every request it receives.

WHY the real executor: `run_direct` drives `Url4Executor(run_shape="direct")` on a `build_world`
world, the exact path a mount call takes on a worker, so the nested branch call, the identity
scope and the cost records are the production ones.
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.main import build_executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import WorldConfig, parse_config
from screamingface_engine.world.factory import SharedWorld, build_world
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.serving import derive_mount_table, engine_route_paths
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import Completed
from url4.wire.subrequest import encode_subrequest

ENDPOINT = "byom_" + "0123456789abcdef" * 2
CLASSIFIER = f"{ENDPOINT}/model_router_v1"
PUBLIC = "anthropic/claude-haiku-4-5"
PROFILE = "expert_router_v1"
LABELS = ("general", "code", "math")
MODELS = {label: f"{ENDPOINT}/{label}" for label in LABELS}
MAX_TOKENS = {"general": 1024, "code": 2048, "math": 512}
CALLER = {"X-User-Email": "caller@x.test"}
TEXT = "a 'b' \"c\" (d) ) e ! f & g %41 + h\nnext line ü 😀 $1"

DETAILS_PATH = "/v1/classifiers/details"
PARAMETERS_PATH = "/v1/model-parameters"
CLASSIFICATIONS_PATH = "/v1/classifications"
CHAT_PATH = "/v1/chat/completions"

GATEWAY_TOML = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/{PUBLIC}"

[[aigateway.models]]
id = "{PUBLIC}"
web_search = false
""" + "".join(
    f"""
[[aigateway.models]]
id = "{MODELS[label]}"
web_search = false
public_schema = false
"""
    for label in LABELS
)

PROFILE_TOML = f"""
[routing.profiles.{PROFILE}]
classifier = "{CLASSIFIER}"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"
""" + "".join(
    f"""
[routing.profiles.{PROFILE}.branches.{label}]
model = "{MODELS[label]}"
max_tokens = {MAX_TOKENS[label]}
"""
    for label in LABELS
)

WORLD_TOML = GATEWAY_TOML + PROFILE_TOML


def world_config(text: str = WORLD_TOML) -> WorldConfig:
    return parse_config(tomllib.loads(text), {}, registry=EMPTY_MODEL_WORLD)


def revision() -> str:
    return world_config().routing[PROFILE].revision


def scores(top: str = "code") -> list[dict[str, Any]]:
    """Classifier scores in a fixed label order with ``top`` clearly highest."""
    return [{"label": label, "score": 0.9 if label == top else 0.05} for label in LABELS]


def classifier_document(**fields: Any) -> dict[str, Any]:
    return {
        "object": "classifier",
        "id": CLASSIFIER,
        "owned_by": ENDPOINT,
        "task": "text-classification",
        "contract": "hf-text-classification-v1",
        "result_contract": "classification-scores-v1",
        "execution_access": "configured",
        **fields,
    }


def max_tokens_rule(**changes: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "request_path": "max_tokens",
        "schema": {"type": "integer", "minimum": 1},
        "provider": {"support": "supported", "source": "declared", "stale": False},
        "gateway": {
            "status": "enabled",
            "projection": "direct",
            "cache_behavior": "keyed",
            "applicable_auth_modes": ["api_key"],
        },
    }
    rule.update(changes)
    return rule


def parameters_document(
    model: str, *, access: str = "configured", rule: object = None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": "mpc_test",
        "model": {"id": model, "gateway_provider": ENDPOINT, "upstream_id": model},
        "context": {
            "scope": "account_connection",
            "auth_mode": "api_key",
            "revision": "ctx_test",
            "source_revision": None,
            "execution_access": access,
        },
        "freshness": {},
        "parameters": {"max_tokens": max_tokens_rule() if rule is None else rule},
        "tools": {},
        "transport": {},
    }


def chat_answer(model: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": f"answer from {model}"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


Step = httpx.Response | BaseException | Callable[[httpx.Request], Any]


@dataclass
class Gateway:
    """Answers each request from ``script[(path, model)]`` when set, else from the defaults.

    ``hold`` names a path whose request waits until cancelled; ``held`` is set once it arrives.
    """

    top: str = "code"
    script: dict[tuple[str, str], Step] = field(default_factory=dict)
    hold: str | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    held: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, model = request.url.path, _model(request)
        if path == self.hold:
            self.held.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        step = self.script.get((path, model))
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, httpx.Response):
            return step
        if step is not None:
            return httpx.Response(200, json=step(request))
        return httpx.Response(200, json=self._default(path, model))

    def _default(self, path: str, model: str) -> dict[str, Any]:
        answers: dict[str, Callable[[], dict[str, Any]]] = {
            DETAILS_PATH: classifier_document,
            PARAMETERS_PATH: lambda: parameters_document(model),
            CLASSIFICATIONS_PATH: lambda: {
                "object": "classification",
                "model": model,
                "contract": "classification-scores-v1",
                "scores": scores(self.top),
            },
        }
        return answers.get(path, lambda: chat_answer(model))()

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handle), base_url="http://aigateway.test"
        )

    def calls(self) -> list[tuple[str, str, str]]:
        """Every request as (method, path, model), in arrival order."""
        return [(r.method, r.url.path, _model(r)) for r in self.requests]

    def posts(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


def _model(request: httpx.Request) -> str:
    if request.method == "GET":
        return request.url.params.get("model", "")
    body = json.loads(request.content)
    return body.get("model", "") if isinstance(body, dict) else ""


def preflight_calls() -> list[tuple[str, str, str]]:
    return [("GET", DETAILS_PATH, CLASSIFIER)] + [
        ("GET", PARAMETERS_PATH, MODELS[label]) for label in LABELS
    ]


def context(profile: str = PROFILE, text: str = TEXT, **fields: Any) -> str:
    return json.dumps(
        {"profile": profile, "input": text, **fields}, ensure_ascii=False, separators=(",", ":")
    )


def query(raw_context: str, intent: str = "route-answer", params: tuple = ()) -> str:
    """The raw query a client sends: url4's encoder, then httpx's wire form."""
    target = encode_subrequest("/route-answer", raw_context, intent, params)
    return httpx.URL(f"http://engine.test{target}").query.decode("ascii")


@dataclass
class Outcome:
    body: str | None
    error: ResolutionError | None
    steps: list[object]

    def document(self) -> dict[str, Any]:
        assert self.error is None, self.error
        assert self.body is not None
        return json.loads(self.body)

    def code(self) -> str:
        assert self.error is not None, self.body
        return str(self.error.code)

    def permanent(self) -> bool:
        assert self.error is not None, self.body
        return self.error.permanent


async def run_direct(
    gateway: Gateway,
    raw_query: str | None = None,
    *,
    scope: RequestScope | None = None,
    config: WorldConfig | None = None,
) -> Outcome:
    """One `/route-answer` direct run on a fresh world over ``gateway``."""
    bound = scope if scope is not None else RequestScope(origin="sync", identity_headers=CALLER)
    target = f"/route-answer?{query(context()) if raw_query is None else raw_query}"
    steps: list[object] = []
    async with gateway.client() as client:
        node, aclose = await build_world(env={}, config=config or world_config(), client=client)
        try:
            with request_scope(bound):
                try:
                    async for step in Url4Executor(node, run_shape="direct").execute(target):
                        steps.append(step)
                except ResolutionError as exc:
                    return Outcome(body=None, error=exc, steps=steps)
        finally:
            if aclose is not None:
                await aclose()
    completed = steps[-1]
    assert isinstance(completed, Completed)
    return Outcome(body=completed.result.body, error=None, steps=steps)


@asynccontextmanager
async def engine(
    gateway: Gateway, world_file: Path, *, warm: bool = False, sync_max_wait_s: float = 5.0
) -> AsyncIterator[tuple[FastAPI, InProcessJobRunner]]:
    """The App over the in-process runner, every world read from ``world_file``.

    Cold, each run's executor reads the file itself; warm, every run shares one node built
    from it, as a worker's shared world is.
    """
    env = {job_env.RUNNER_CONFIG: str(world_file)}
    stream = InMemoryEventStream()
    async with gateway.client() as client:
        node, aclose = await build_world(env=env, client=client)
        if warm:
            provider = lambda: SharedWorld(io=node, section=None)  # noqa: E731 - binding read
            runner = InProcessJobRunner(
                stream, lambda job: build_executor({**job, **env}, shared_world_provider=provider)
            )
        else:
            runner = InProcessJobRunner(
                stream, lambda job: build_executor({**job, **env}, client=client)
            )
        app = create_app(
            Settings(jwt_secret="routing-hosted-secret-000000000", sync_max_wait_s=sync_max_wait_s),
            stream=stream,
            job_runner=runner,
        )
        # WHY the production derivation: it applies `public_schema = false` to the private routes.
        register_mounts(
            app, await derive_mount_table(env=env, engine_routes=engine_route_paths(app))
        )
        try:
            yield app, runner
        finally:
            await runner.aclose()
            if aclose is not None:
                await aclose()


async def call(app: FastAPI, raw_query: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://engine.test"
    ) as caller:
        return await caller.get(f"/route-answer?{raw_query}", headers={**CALLER, **headers})


def write_world(directory: Path, text: str = WORLD_TOML) -> Path:
    path = directory / "url4.toml"
    path.write_text(text)
    return path
