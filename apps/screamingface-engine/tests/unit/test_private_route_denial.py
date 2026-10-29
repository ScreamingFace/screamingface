"""A caller without a grant cannot tell a private route from an undeclared one (OME-1770 review).

FEATURE: hosted BYOM, Unit 2. A private configured-endpoint route is executable but unpublished.
The Gateway refuses an ungranted account its target as an unknown provider.

INVARIANT: for a caller the Gateway does not grant, a private route answers exactly as a route
this Engine never declared.
- The direct mount answers the framework's 404, with the same status, body and headers, without
  identity, on every other method, for a refused run, and before every pre-queue refusal.
- A run that calls the route ends with url4's own undeclared-route error, cold and warm.
- `/metrics` counts the answer as `<unmatched>`, never as the private route.

WHY the grant check runs only on a refusal: a granted caller's successful call must cost no extra
Gateway round trip, and only a refusal can reveal that the route exists.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from test_private_route_run_frames import _replay

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.catalog.port import (
    CatalogError,
    Credential,
    ModelNotInstalled,
    ModelParameterResponse,
)
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import RUN_HEADER, register_mounts
from screamingface_engine.runner.main import build_executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import SharedWorld, build_world
from screamingface_engine.world.serving import MountDescriptor, MountTable
from url4.streaming.protocol import (
    ErrorInfo,
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for

pytestmark = pytest.mark.no_default_scope

_ENDPOINT = "byom_" + "a" * 32
_PRIVATE = f"{_ENDPOINT}/model_v1"
_UNDECLARED = "byom_" + "f" * 32 + "/model_v1"
_PUBLIC = "anthropic/claude-haiku-4-5"
_EMAIL = {"X-User-Email": "outsider@example.com"}
_OTHER_METHODS = ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _answer(resp: httpx.Response) -> tuple[int, bytes, list[tuple[str, str]]]:
    return resp.status_code, resp.content, sorted(resp.headers.items())


# --- the direct mount -------------------------------------------------------------------------


class _Runner:
    """Answers each direct run with one fixed terminal: success, or a failure with `code`."""

    def __init__(self, stream: InMemoryEventStream, code: str | None) -> None:
        self._stream, self._code = stream, code
        self.targets: list[str] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **_: Any) -> str:
        self.targets.append(url4)
        source = source_for(topic)
        if self._code is None:
            data = TerminatedData(status="succeeded")
            await self._stream.publish(
                topic,
                ResultEvent(id="r", source=source, subject=topic, data=ResultData(body="ok")),
            )
        else:
            error = ErrorInfo(code=self._code, message="refused", permanent=True)
            data = TerminatedData(status="failed", error=error)
        await self._stream.publish(
            topic, TerminatedEvent(id="t", source=source, subject=topic, data=data)
        )
        return f"job-{topic}"

    async def stop(self, topic: str) -> None:
        pass

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> str:
        return "running"


class _Grants:
    """The details source: a granted caller gets 200, any other the not-installed refusal."""

    def __init__(self, *, granted: bool, error: CatalogError | None = None) -> None:
        self._granted, self._error = granted, error
        self.seen: list[str] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.seen.append(model)
        if self._error is not None:
            raise self._error
        if not self._granted:
            raise ModelNotInstalled(model)
        return ModelParameterResponse(status=200, content=b"{}")

    async def aclose(self) -> None:
        pass


def _mounted(
    *, code: str | None = None, grants: _Grants | None = None, require_identity: bool = True
) -> tuple[FastAPI, _Runner]:
    stream = InMemoryEventStream()
    runner = _Runner(stream, code)
    app = create_app(
        Settings(jwt_secret="private-route-denial-secret-0000000"),
        stream=stream,
        job_runner=runner,  # type: ignore[arg-type]
        model_parameters=grants,  # type: ignore[arg-type]
    )
    table = MountTable(
        mounts=(
            MountDescriptor(f"/{_PUBLIC}", "endpoint", None),
            MountDescriptor(f"/{_PRIVATE}", "endpoint", None, public_schema=False),
        ),
        config_digest=None,
    )
    register_mounts(app, table, require_identity=require_identity)
    return app, runner


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://engine.test")


async def _both(app: FastAPI, method: str, suffix: str, headers: dict[str, str]) -> tuple[Any, Any]:
    async with _client(app) as client:
        private = await client.request(method, f"/{_PRIVATE}{suffix}", headers=headers)
        undeclared = await client.request(method, f"/{_UNDECLARED}{suffix}", headers=headers)
    return private, undeclared


@pytest.mark.asyncio
async def test_without_identity_a_private_mount_answers_as_an_undeclared_route() -> None:
    app, runner = _mounted(grants=_Grants(granted=False))

    private, undeclared = await _both(app, "GET", "?q=('')!'go'", {})

    assert _answer(private) == _answer(undeclared)
    assert private.status_code == 404
    assert runner.targets == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", _OTHER_METHODS)
@pytest.mark.parametrize("headers", [{}, _EMAIL], ids=["anonymous", "identified"])
async def test_another_method_on_a_private_mount_answers_as_an_undeclared_route(
    method: str, headers: dict[str, str]
) -> None:
    app, _ = _mounted(grants=_Grants(granted=False))

    private, undeclared = await _both(app, method, "", headers)

    assert _answer(private) == _answer(undeclared)


@pytest.mark.asyncio
async def test_a_refused_run_answers_as_an_undeclared_route_and_names_no_run() -> None:
    """STORY: as a caller without this endpoint's grant, calling its route by a guess tells me
    nothing a route the Engine never declared would not."""
    grants = _Grants(granted=False)
    app, runner = _mounted(code="endpoint_not_found", grants=grants)

    private, undeclared = await _both(app, "GET", "?q=('')!'go'", _EMAIL)

    assert _answer(private) == _answer(undeclared)
    assert RUN_HEADER not in private.headers
    assert runner.targets == [f"/{_PRIVATE}?q=('')!'go'"]
    assert grants.seen == [_PRIVATE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "headers"),
    [
        ("", {}),
        ("?q=('')!'go'", {"X-Profile": "work"}),
        ("?q=('')!'go'", {"X-Answer-Seed": "not-a-number"}),
        ("?q=('')!'go'", {"X-Capture": "true"}),
        ("?q=" + "a" * 9000, {}),
    ],
    ids=["missing-intent", "x-profile", "malformed-seed", "frozen-copy", "too-long"],
)
async def test_a_pre_queue_refusal_answers_as_an_undeclared_route(
    suffix: str, headers: dict[str, str]
) -> None:
    grants = _Grants(granted=False)
    app, runner = _mounted(grants=grants)

    private, undeclared = await _both(app, "GET", suffix, {**_EMAIL, **headers})

    assert _answer(private) == _answer(undeclared)
    assert runner.targets == []
    assert grants.seen == [_PRIVATE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grants",
    [None, _Grants(granted=False, error=CatalogError())],
    ids=["no-details-source", "details-unavailable"],
)
async def test_a_grant_that_cannot_be_proven_is_denied(grants: _Grants | None) -> None:
    app, _ = _mounted(code="endpoint_not_found", grants=grants)

    private, undeclared = await _both(app, "GET", "?q=('')!'go'", _EMAIL)

    assert _answer(private) == _answer(undeclared)


@pytest.mark.asyncio
async def test_a_granted_caller_keeps_the_real_refusal() -> None:
    grants = _Grants(granted=True)
    app, _ = _mounted(code="aigateway_http_400", grants=grants)

    async with _client(app) as client:
        missing = await client.get(f"/{_PRIVATE}", headers=_EMAIL)
        failed = await client.get(f"/{_PRIVATE}?q=('')!'go'", headers=_EMAIL)

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "missing_intent"
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "aigateway_http_400"
    assert RUN_HEADER in failed.headers
    assert grants.seen == [_PRIVATE, _PRIVATE]


@pytest.mark.asyncio
async def test_a_granted_success_asks_the_gateway_nothing_extra() -> None:
    grants = _Grants(granted=True)
    app, _ = _mounted(grants=grants)

    async with _client(app) as client:
        resp = await client.get(f"/{_PRIVATE}?q=('')!'go'", headers=_EMAIL)

    assert resp.status_code == 200
    assert grants.seen == []


@pytest.mark.asyncio
async def test_local_mode_still_serves_a_private_mount_without_identity() -> None:
    app, runner = _mounted(require_identity=False)

    async with _client(app) as client:
        resp = await client.get(f"/{_PRIVATE}?q=('')!'go'")

    assert resp.status_code == 200
    assert runner.targets == [f"/{_PRIVATE}?q=('')!'go'"]


@pytest.mark.asyncio
async def test_metrics_count_a_denial_as_unmatched() -> None:
    app, _ = _mounted(code="endpoint_not_found", grants=_Grants(granted=False))

    async with _client(app) as client:
        await client.get(f"/{_PRIVATE}?q=('')!'go'")
        await client.post(f"/{_PRIVATE}")
        await client.get(f"/{_PRIVATE}?q=('')!'go'", headers=_EMAIL)
        metrics = (await client.get("/metrics")).text

    assert _ENDPOINT not in metrics
    assert "<private>" not in metrics
    assert 'method="GET",path="<unmatched>",status="404"} 2.0' in metrics
    assert 'method="POST",path="<unmatched>",status="404"} 1.0' in metrics


# --- a run that calls the private route -------------------------------------------------------


def _world() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_PUBLIC,
            models=(
                ModelSpec(id=_PUBLIC, web_search=False),
                ModelSpec(id=_PRIVATE, web_search=False, public_schema=False),
            ),
        )
    )


def _gateway(denial: dict[str, Any]) -> httpx.MockTransport:
    """The Gateway: it refuses the private target with `denial`, and answers every other call."""

    def handle(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == _PRIVATE:
            return httpx.Response(400, json=denial)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    return httpx.MockTransport(handle)


@asynccontextmanager
async def _engine(*, warm: bool, denial: dict[str, Any]) -> AsyncIterator[FastAPI]:
    stream = InMemoryEventStream()
    async with httpx.AsyncClient(
        transport=_gateway(denial), base_url="http://aigateway.test"
    ) as client:
        aclose = None
        if warm:
            node, aclose = await build_world(env={}, config=_world(), client=client)
            provider = lambda: SharedWorld(io=node, section=None)  # noqa: E731 - binding read
            runner = InProcessJobRunner(
                stream, lambda env: build_executor(env, shared_world_provider=provider)
            )
        else:
            runner = InProcessJobRunner(
                stream, lambda env: build_executor(env, _world(), client=client)
            )
        app = create_app(
            Settings(jwt_secret="private-route-denial-secret-0000000"),
            stream=stream,
            job_runner=runner,
        )
        try:
            yield app
        finally:
            await runner.aclose()
            if aclose is not None:
                await aclose()


async def _run(app: FastAPI, route: str) -> tuple[httpx.Response, list[dict[str, Any]]]:
    async with _client(app) as caller:
        token = (await caller.post("/token")).json()["token"]
        resp = await caller.get(
            "/",
            params={"q": f"/{route}('hi')!'go'"},
            headers={**_EMAIL, "URL4-Capability": token, "Prefer": "wait=5"},
        )
    return resp, await _replay(app, token)


def _error(frames: list[dict[str, Any]]) -> dict[str, Any]:
    terminated = frames[-1]
    assert terminated["type"] == "ai.url4.terminated"
    return terminated["data"]["error"]


_PER_RUN = frozenset({"start", "end", "trace_id"})
"""Values every run has its own of: span times and the trace id."""


def _seen(value: Any, *, route: str) -> Any:
    """What the caller sees, with per-run values dropped and `route` written as the private one."""
    if isinstance(value, dict):
        return {k: _seen(v, route=route) for k, v in value.items() if k not in _PER_RUN}
    if isinstance(value, list):
        return [_seen(v, route=route) for v in value]
    return value.replace(route, _PRIVATE) if isinstance(value, str) else value


def _frames_seen(frames: list[dict[str, Any]], *, route: str) -> list[Any]:
    return [(f["type"], _seen(f.get("data"), route=route)) for f in frames]


@pytest.mark.asyncio
@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
async def test_a_refused_private_call_ends_as_an_undeclared_route(warm: bool) -> None:
    async with _engine(warm=warm, denial={"detail": f"unknown provider: {_ENDPOINT}"}) as app:
        private, private_frames = await _run(app, _PRIVATE)
        undeclared, undeclared_frames = await _run(app, _UNDECLARED)

    assert private.status_code == undeclared.status_code
    assert _seen(private.json(), route=_PRIVATE) == _seen(undeclared.json(), route=_UNDECLARED)
    assert _frames_seen(private_frames, route=_PRIVATE) == _frames_seen(
        undeclared_frames, route=_UNDECLARED
    )
    assert (_error(private_frames)["code"], _error(private_frames)["permanent"]) == (
        "endpoint_not_found",
        True,
    )
    assert "unknown provider" not in json.dumps(private_frames) + private.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denial",
    [
        {"detail": "unknown provider: byom_" + "b" * 32},
        {"detail": "seed is not supported"},
        {"detail": {"code": "unsupported_parameter", "message": "seed is not supported"}},
    ],
    ids=["another-provider", "another-reason", "structured"],
)
async def test_any_other_gateway_refusal_of_a_private_call_is_kept(denial: dict[str, Any]) -> None:
    async with _engine(warm=False, denial=denial) as app:
        _, frames = await _run(app, _PRIVATE)

    assert _error(frames)["code"] != "endpoint_not_found"
