"""`GET /classify?q=` through the real App, the in-process runner and a fake Gateway (OME-1795).

FEATURE: hosted BYOM, Unit 3. One `/classify` serves every classifier the caller is granted,
cold and warm, with no prior listing and no reconfiguration. The App refuses before any run what
it can (the 8 KiB limit, a frozen-copy header), the handler refuses a seed before any Gateway
call, and a short client wait ends in the Engine's own timeout answer whatever its server limit.

STORY: as a granted caller with two classifiers I call one Engine path for each, and the answer is
my classifier's labels and scores.

WHY substitutes: this proves the Engine half on a fake Gateway, with `InProcessJobRunner` in place
of the queue and a worker. The hosted check through Linux NATS/JetStream, a real worker and the
real Gateway stays pending; nothing here claims it.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.rest.mounts import RUN_HEADER, register_mounts
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.main import build_executor
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.accounting import UNPRICED
from screamingface_engine.world.classification import CLASSIFICATIONS_PATH
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import SharedWorld, build_world
from screamingface_engine.world.serving import MountTable, mount_descriptors
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import CostUsageData
from url4.wire.subrequest import encode_subrequest

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_PUBLIC = "anthropic/claude-haiku-4-5"
_FIRST = "byom_" + "0123456789abcdef" * 2 + "/classifier_v1"
_SECOND = "byom_" + "fedcba9876543210" * 2 + "/sentiment"
_CALLER = "caller@x.test"
_EMAIL = {"X-User-Email": _CALLER}
_LIMIT = 8192 - len("/classify?")


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_PUBLIC,
            models=(ModelSpec(id=_PUBLIC, web_search=False),),
        )
    )


def _query(model: str, text: str) -> str:
    """The raw query a client sends: the SDK's compact context, url4's encoder, httpx's wire."""
    context = json.dumps({"model": model, "input": text}, ensure_ascii=False, separators=(",", ":"))
    target = encode_subrequest("/classify", context, "classify")
    return httpx.URL(f"http://engine.test{target}").query.decode("ascii")


def _scores(model: str) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": model,
        "contract": "classification-scores-v1",
        "scores": [{"label": "POSITIVE", "score": 0.75}, {"label": "NEGATIVE", "score": 0.25}],
    }


class _Gateway:
    """Answers each classification with the requested model's scores; records every request.

    With ``hang`` set it never answers, and notes when the waiting request is cancelled.
    """

    def __init__(self, *, hang: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self._hang = hang
        self.cancelled = asyncio.Event()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        return httpx.Response(200, json=_scores(json.loads(request.content)["model"]))


@asynccontextmanager
async def _engine(
    gateway: _Gateway, *, warm: bool = False, sync_max_wait_s: float = 5.0
) -> AsyncIterator[tuple[FastAPI, InProcessJobRunner]]:
    stream = InMemoryEventStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        node, aclose = await build_world(env={}, config=_config(), client=client)
        if warm:
            provider = lambda: SharedWorld(io=node, section=None)  # noqa: E731 - binding read
            runner = InProcessJobRunner(
                stream, lambda env: build_executor(env, shared_world_provider=provider)
            )
        else:
            runner = InProcessJobRunner(
                stream, lambda env: build_executor(env, _config(), client=client)
            )
        app = create_app(
            Settings(jwt_secret="classify-hosted-secret-00000000", sync_max_wait_s=sync_max_wait_s),
            stream=stream,
            job_runner=runner,
        )
        register_mounts(app, MountTable(mounts=mount_descriptors(node), config_digest=None))
        try:
            yield app, runner
        finally:
            await runner.aclose()
            if aclose is not None:
                await aclose()


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://engine.test")


async def _call(app: FastAPI, query: str, **headers: str) -> httpx.Response:
    async with _client(app) as caller:
        return await caller.get(f"/classify?{query}", headers={**_EMAIL, **headers})


def _error(resp: httpx.Response) -> dict[str, Any]:
    return resp.json()["error"]


async def _ends(runner: InProcessJobRunner, topic: str) -> bool:
    """Whether the run's task finishes within a few seconds; the cancelled task still has to
    unwind through the run lifecycle after the Gateway request is cancelled."""
    for _ in range(500):
        if not await runner.exists(topic):
            return True
        await asyncio.sleep(0.01)
    return False


# --- two classifiers, cold and warm ---------------------------------------------------------------


@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
async def test_one_path_serves_two_classifiers_with_the_callers_identity(warm: bool) -> None:
    gateway = _Gateway()
    async with _engine(gateway, warm=warm) as (app, _):
        first = await _call(app, _query(_FIRST, "I loved it"))
        second = await _call(app, _query(_SECOND, "Ça ira + bien & vite"))

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.headers["content-type"].startswith("application/json")
    assert (first.json(), second.json()) == (_scores(_FIRST), _scores(_SECOND))
    # No catalog, details or admission call: the model ID in the request is enough.
    assert [request.url.path for request in gateway.requests] == [CLASSIFICATIONS_PATH] * 2
    assert [json.loads(request.content) for request in gateway.requests] == [
        {"model": _FIRST, "input": "I loved it"},
        {"model": _SECOND, "input": "Ça ira + bien & vite"},
    ]
    for request in gateway.requests:
        assert request.headers["X-User-Email"] == _CALLER
        assert "Authorization" not in request.headers


# --- what the App refuses before any run ----------------------------------------------------------


async def test_the_encoded_limit_admits_8182_query_bytes_and_refuses_one_more() -> None:
    """Spec 3.4: with this model ID's length, 8075 ASCII letters fill the 8 KiB exactly."""
    gateway = _Gateway()
    fits = "a" * 8075
    assert len(_query(_FIRST, fits)) == _LIMIT == 8182

    async with _engine(gateway) as (app, _):
        accepted = await _call(app, _query(_FIRST, fits))
        refused = await _call(app, _query(_FIRST, fits + "a"))

    assert accepted.status_code == 200
    assert (refused.status_code, _error(refused)["code"]) == (414, "uri_too_long")
    assert [json.loads(request.content)["input"] for request in gateway.requests] == [fits]


@pytest.mark.parametrize(
    "escape", ["%FF", "%ED%A0%80", "%C3"], ids=["not-utf8", "encoded-surrogate", "truncated"]
)
async def test_a_percent_escape_that_is_not_utf8_is_refused_before_any_gateway_call(
    escape: str,
) -> None:
    """WHY (decision 10): url4 decodes such an escape to U+FFFD, so the classifier would be paid
    for a text the caller never sent. A valid escape of the same text is the control."""
    gateway = _Gateway()
    query = _query(_FIRST, "zz-HOLE-zz")
    assert "zz-HOLE-zz" in query

    async with _engine(gateway) as (app, _):
        refused = await _call(app, query.replace("HOLE", escape))
        control = await _call(app, query.replace("HOLE", "%C3%A9"))

    assert (refused.status_code, _error(refused)["code"]) == (400, "malformed_source")
    assert control.status_code == 200
    assert [json.loads(request.content)["input"] for request in gateway.requests] == ["zz-é-zz"]


async def test_an_answer_seed_is_refused_before_any_gateway_call() -> None:
    gateway = _Gateway()
    async with _engine(gateway) as (app, _):
        resp = await _call(app, _query(_FIRST, "hello"), **{"X-Answer-Seed": "7"})

    assert (resp.status_code, _error(resp)["code"]) == (400, "classification_unsupported")
    assert gateway.requests == []


@pytest.mark.parametrize(
    "header",
    [{"X-Capture": "true"}, {"X-Replay-Frozen-Copy": "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"}],
    ids=["capture", "replay"],
)
async def test_a_frozen_copy_header_is_refused_by_the_app_with_no_gateway_request(
    header: dict[str, str],
) -> None:
    gateway = _Gateway()
    async with _engine(gateway) as (app, _):
        resp = await _call(app, _query(_FIRST, "hello"), **header)

    assert (resp.status_code, _error(resp)["code"]) == (400, "capture_unsupported")
    assert RUN_HEADER not in resp.headers
    assert gateway.requests == []


# --- the wait bound -------------------------------------------------------------------------------


async def test_a_short_wait_ends_in_the_engines_timeout_whatever_the_server_limit() -> None:
    """The Engine half of the SDK's wait contract: with a 60 second server limit, `Prefer:
    wait=0.2` bounds the call, and its run is stopped, so no Gateway request outlives it."""
    gateway = _Gateway(hang=True)
    async with _engine(gateway, sync_max_wait_s=60.0) as (app, runner):
        started = time.monotonic()
        resp = await _call(app, _query(_FIRST, "hello"), Prefer="wait=0.2")
        elapsed = time.monotonic() - started
        await asyncio.wait_for(gateway.cancelled.wait(), timeout=5)
        stopped = await _ends(runner, resp.headers[RUN_HEADER])

    assert (resp.status_code, _error(resp)["code"]) == (504, "timeout")
    assert elapsed < 5
    assert [request.url.path for request in gateway.requests] == [CLASSIFICATIONS_PATH]
    assert stopped


# --- the run stays unpriced -----------------------------------------------------------------------


async def test_a_classification_reports_one_unpriced_call() -> None:
    """E8 as amended (owner, 2026-10-30): the dispatched call reports one record whose cost is
    unknown, so the run is unpriced however it is combined. Its zero counts are the sink's
    required fields, not measurements."""
    gateway = _Gateway()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        node, aclose = await build_world(env={}, config=_config(), client=client)
        with request_scope(RequestScope(origin="sync", identity_headers=_EMAIL)):
            steps = [
                step
                async for step in Url4Executor(node, run_shape="direct").execute(
                    f"/classify?{_query(_FIRST, 'hello')}"
                )
            ]
        if aclose is not None:
            await aclose()

    completed = steps[-1]
    assert isinstance(completed, Completed) and completed.result.body is not None
    assert json.loads(completed.result.body) == _scores(_FIRST)
    frames = [s.payload for s in steps if isinstance(s, Traced)]
    (own,) = [f for f in frames if isinstance(f, CostUsageData) and f.scope == "self"]
    assert (own.model, own.pricing_version) == (_FIRST, UNPRICED)
    assert completed.subtree_cost.pricing_version == UNPRICED
    assert completed.subtree_cost.usage.input_tokens == 0


# --- the text arrives as sent ---------------------------------------------------------------------


async def test_a_dollar_reference_in_the_input_reaches_the_gateway_literally() -> None:
    """A direct call substitutes nothing: `$text`, `$item` and `$1` are the caller's characters."""
    text = "$text and $item, then $1 $"
    gateway = _Gateway()
    async with _engine(gateway) as (app, _):
        resp = await _call(app, _query(_FIRST, text))

    assert resp.status_code == 200
    assert [json.loads(request.content) for request in gateway.requests] == [
        {"model": _FIRST, "input": text}
    ]


async def test_a_lone_surrogate_is_refused_by_the_app_with_no_gateway_request() -> None:
    """JSON can spell a lone surrogate, which no UTF-8 body can carry; the caller's request is
    malformed, and nothing is sent."""
    context = json.dumps({"model": _FIRST, "input": "a\ud800b"}, separators=(",", ":"))
    target = encode_subrequest("/classify", context, "classify")
    query = httpx.URL(f"http://engine.test{target}").query.decode("ascii")
    gateway = _Gateway()
    async with _engine(gateway) as (app, _):
        resp = await _call(app, query)

    assert (resp.status_code, _error(resp)["code"]) == (400, "malformed_source")
    assert gateway.requests == []
