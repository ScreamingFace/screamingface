"""FX-61/FX-64 — every producer binds the caller's scope, and the trace, before a handler runs.

# WHY this file exists. `tests/conftest.py` binds an anonymous scope around every test, so a
# test that drives a production path could pass because the HARNESS bound a scope, not because
# the producer did. Every test here carries `no_default_scope`, which turns that fixture off:
# each one first proves nothing is bound, then drives one real producer — the run path, the node
# tier, local sync — and proves the handler saw that producer's own scope (U1-M1).
#
# FX-64: the trace has ONE carrier, `trace_scope`. The sync producers bind it from the validated
# inbound `traceparent`; the scope no longer carries a copy the connector could prefer.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_aigateway_connector import _MockAigateway
from test_node_tier import _KEY, _NEVER_SPILLS, _node_client
from test_node_tier_dispatch_fixes import _answering, _direct_tier

from screamingface_engine import job_env
from screamingface_engine.local import _LocalNodeMount
from screamingface_engine.request_scope import RequestScope, RequestScopeError, current_scope
from screamingface_engine.runner.main import build_executor
from screamingface_engine.trace_scope import current_traceparent
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.node_tier import NodeTierSettings, build_node_tier
from url4.dag import run as url4_run

pytestmark = pytest.mark.no_default_scope

MODEL = "anthropic/claude-haiku-4-5"
_TRACE = "00-" + "e" * 32 + "-" + "f" * 16 + "-01"
_FAST = NodeTierSettings(request_timeout_s=5.0, aigateway_timeout_s=4.0)


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


def _assert_nothing_bound() -> None:
    """The marker's promise: no harness scope, so only a producer can make a handler work."""
    with pytest.raises(RequestScopeError):
        current_scope()
    assert current_traceparent() is None


class _Recorder:
    """An inner ASGI app that records what a handler would read, then answers 200."""

    def __init__(self) -> None:
        self.scope: RequestScope | None = None
        self.traceparent: str | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.scope = current_scope()
        self.traceparent = current_traceparent()
        await _answering(200, {"ok": True})(scope, receive, send)


def test_the_marker_turns_the_harness_scope_off() -> None:
    _assert_nothing_bound()


@pytest.mark.asyncio
async def test_a_handler_called_with_no_producer_raises_request_scope_error() -> None:
    """AC5: with nothing bound, the handler refuses — it never sends an anonymous call."""
    _assert_nothing_bound()
    gw = _MockAigateway((MODEL,))
    cfg = AigatewayConfig(models=gw.models, default_model=MODEL)

    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            with pytest.raises(RequestScopeError):
                await url4_run(f"/{MODEL}('ctx')!'go'", io=world.node)
        finally:
            await world.aclose()

    assert gw.posts_to(MODEL) == []


# --- producer 1: the run path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_run_path_binds_the_scope_before_the_handler_runs() -> None:
    _assert_nothing_bound()
    gw = _MockAigateway((MODEL,))
    env = {
        **job_env.identity_to_env({"X-User-Email": "run@x.test"}),
        job_env.AIGATEWAY_PROFILE: "run-profile",
    }

    async with gw.client() as client:
        executor = build_executor(env, _config(), client=client)
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'"):
            pass

    (outbound,) = gw.posts_to(MODEL)
    assert outbound.headers["X-User-Email"] == "run@x.test"
    assert outbound.headers["X-Profile"] == "run-profile"
    _assert_nothing_bound()  # the run's binding is reset once it ends


# --- producer 2: the node tier -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_node_tier_binds_the_scope_and_the_trace_before_the_handler_runs() -> None:
    _assert_nothing_bound()
    recorder = _Recorder()

    async with _node_client(_direct_tier(recorder)) as node:
        response = await node.get(
            "/m", headers={"X-User-Email": "a@x.test", "X-Profile": "p", "traceparent": _TRACE}
        )

    assert response.status_code == 200, response.text
    assert recorder.scope is not None
    assert dict(recorder.scope.identity_headers) == {"X-User-Email": "a@x.test"}
    assert recorder.scope.profile == "p"
    assert recorder.scope.origin == "sync"
    assert recorder.traceparent == _TRACE
    _assert_nothing_bound()


@pytest.mark.asyncio
async def test_the_node_tier_binds_no_trace_for_a_malformed_traceparent() -> None:
    """`valid_traceparent` stays strict: a malformed header is dropped, never forwarded."""
    recorder = _Recorder()

    async with _node_client(_direct_tier(recorder)) as node:
        await node.get("/m", headers={"X-User-Email": "a@x.test", "traceparent": "00-bad"})

    assert recorder.scope is not None
    assert recorder.traceparent is None


@pytest.mark.asyncio
async def test_a_node_tier_mount_call_reaches_aigateway_with_the_callers_identity_and_trace() -> (
    None
):
    """The node tier end to end, with no harness scope: the outbound call carries the inbound
    caller's identity and trace, and the trace comes from `trace_scope` (FX-64)."""
    _assert_nothing_bound()
    gw = _MockAigateway((MODEL,))
    async with gw.client() as client:
        tier = await build_node_tier(
            env={},
            config=_config(),
            client=client,
            settings=_FAST,
            artifact_store=_NEVER_SPILLS,
            artifact_signing_key=_KEY,
        )
        try:
            async with _node_client(tier) as node:
                response = await node.get(
                    f"/{MODEL}",
                    params={"q": "('')!'go'"},
                    headers={"X-User-Email": "a@x.test", "traceparent": _TRACE},
                )
        finally:
            await tier.aclose()

    assert response.status_code == 200, response.text
    (outbound,) = gw.posts_to(MODEL)
    assert outbound.headers["X-User-Email"] == "a@x.test"
    assert outbound.headers["traceparent"] == _TRACE


# --- producer 3: local sync (`_LocalNodeMount`) ------------------------------------------------


def _local_client(inner: Any) -> httpx.AsyncClient:
    mount = _LocalNodeMount({"asgi": inner})
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=mount), base_url="http://app.test")


@pytest.mark.asyncio
async def test_the_local_sync_mount_binds_the_scope_and_the_trace_before_the_handler_runs() -> None:
    _assert_nothing_bound()
    recorder = _Recorder()

    async with _local_client(recorder) as client:
        response = await client.get(
            "/m",
            headers={"X-User-Email": "local@x.test", "X-Answer-Seed": "5", "traceparent": _TRACE},
        )

    assert response.status_code == 200, response.text
    assert recorder.scope is not None
    assert dict(recorder.scope.identity_headers) == {"X-User-Email": "local@x.test"}
    assert recorder.scope.answer_seed == 5
    assert recorder.scope.origin == "sync"
    assert recorder.traceparent == _TRACE
    _assert_nothing_bound()


@pytest.mark.asyncio
async def test_the_local_sync_mount_binds_no_trace_when_the_caller_sent_none() -> None:
    recorder = _Recorder()

    async with _local_client(recorder) as client:
        await client.get("/m", headers={"X-User-Email": "local@x.test"})

    assert recorder.scope is not None
    assert recorder.traceparent is None
