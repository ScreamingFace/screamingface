"""F2 — the request scope: per-caller state travels with the request, never on the handler.

# WHY this file exists. Unit 1 turns a per-run `_ModelEndpoint` into a stateless handler that
# reads its caller's identity, profile, cache policy and answer seed from a `request_scope`
# ContextVar (prd/01 §2 F2). The defining requirement is concurrency (AC2): two requests through
# ONE handler must never see each other's scope. T1 below proves the old code could not do that
# and guards the new code; T3 and T4 pin the ContextVar's two load-bearing properties (fails
# loudly when unbound, inherits into spawned tasks); T6 pins the child-boot producer.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from collections.abc import Mapping
from typing import Any, cast

import pytest
from test_aigateway_connector import _MockAigateway
from test_answer_seed_threading import _candidate_wrapped

from screamingface_engine import job_env
from screamingface_engine.request_scope import (
    RequestScope,
    RequestScopeError,
    current_scope,
    request_scope,
)
from screamingface_engine.runner.main import (
    RunnerConfigError,
    build_executor,
    request_scope_from_env,
)
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _ModelEndpoint,
    build_aigateway_world,
)
from url4.dag import run as url4_run
from url4.io.layer import IOLayer
from url4.streaming.protocol import CachePolicy

MODEL = "anthropic/claude-haiku-4-5"

_SCOPE_A = RequestScope(
    origin="run",
    identity_headers={"X-User-Email": "a@x.test"},
    profile="profile-a",
    answer_seed=11,
    cache=CachePolicy(participate=False),
)
_SCOPE_B = RequestScope(
    origin="run",
    identity_headers={"X-User-Email": "b@x.test"},
    profile="profile-b",
    answer_seed=22,
    cache=CachePolicy(participate=True),
)


async def _run_under(scope: RequestScope, node: IOLayer, context: str) -> None:
    """One answer call made inside ``scope`` — the shape a producer guarantees in production."""
    with request_scope(scope):
        await url4_run(_candidate_wrapped(context), io=node)


# --- T1 / AC2: two concurrent callers through one handler never share scope -------------------


@pytest.mark.asyncio
async def test_two_concurrent_requests_through_one_handler_keep_their_own_scope() -> None:
    """THE defining test (prd/01 T1, AC2).

    One world, one `_ModelEndpoint`, two concurrent calls bound to different scopes. With the
    pre-F2 handler this fails: identity, profile, seed and cache live on `self`, so both calls
    share whatever was pinned at build time (here, nothing). It is the regression guard for the
    refactor, not merely a demonstration of ContextVars.
    """
    gw = _MockAigateway((MODEL,))
    cfg = AigatewayConfig(models=gw.models, default_model=MODEL)

    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        await asyncio.gather(
            _run_under(_SCOPE_A, world.node, "ctx-a"),
            _run_under(_SCOPE_B, world.node, "ctx-b"),
        )

    by_context = {
        json.loads(request.content)["messages"][-1]["content"]: request
        for request in gw.posts_to(MODEL)
    }
    a, b = by_context["ctx-a"], by_context["ctx-b"]

    assert a.headers["X-User-Email"] == "a@x.test"
    assert a.headers["X-Profile"] == "profile-a"
    assert b.headers["X-User-Email"] == "b@x.test"
    assert b.headers["X-Profile"] == "profile-b"

    body_a, body_b = json.loads(a.content), json.loads(b.content)
    assert body_a["seed"] == 11
    assert body_b["seed"] == 22
    assert body_a["cache"] == {"use-cache": False}
    assert "cache" not in body_b


# --- T3 / AC5: an unbound scope fails loudly, never a silent default --------------------------


def test_current_scope_with_nothing_bound_raises_a_named_engine_error() -> None:
    """A silent default would send an anonymous, unprofiled, unseeded call and bill someone.

    Run inside a FRESH `contextvars.Context` so this test is immune to any scope the test
    harness binds around a test (see `tests/conftest.py`).
    """
    context = contextvars.Context()

    with pytest.raises(RequestScopeError):
        context.run(current_scope)


def test_current_scope_never_returns_a_default_constructed_scope() -> None:
    context = contextvars.Context()

    with pytest.raises(RequestScopeError):
        scope = context.run(current_scope)
        assert scope is not None  # unreachable; documents "no default" explicitly


# --- T4 / AC4: spawned tasks inherit, siblings stay isolated ----------------------------------


@pytest.mark.asyncio
async def test_a_spawned_task_inherits_the_bound_scope() -> None:
    async def read_seed() -> int | None:
        return current_scope().answer_seed

    with request_scope(RequestScope(origin="run", answer_seed=5)):
        async with asyncio.TaskGroup() as group:
            child = group.create_task(read_seed())

    assert child.result() == 5


@pytest.mark.asyncio
async def test_sibling_tasks_bound_to_different_scopes_stay_isolated() -> None:
    async def read_in(scope: RequestScope) -> int | None:
        with request_scope(scope):
            # A suspension point, so a shared/leaked context would have to show up here.
            await asyncio.sleep(0)
            return current_scope().answer_seed

    results = await asyncio.gather(
        read_in(RequestScope(origin="run", answer_seed=1)),
        read_in(RequestScope(origin="run", answer_seed=2)),
    )

    assert results == [1, 2]


def test_the_scope_is_restored_on_exit() -> None:
    """A finished request must not leak its caller state to the next one in the same task."""
    with request_scope(RequestScope(origin="run", answer_seed=7)):
        assert current_scope().answer_seed == 7

    context = contextvars.Context()
    with pytest.raises(RequestScopeError):
        context.run(current_scope)


# --- T2 / AC3: no caller state survives a request on any long-lived object -------------------

_SCOPE_FIELD_NAMES = frozenset(
    {
        "identity_headers",
        "profile",
        "answer_seed",
        "cache",
        "origin",
        "traceparent",
        "_identity_headers",
        "_profile",
        "_answer_seed",
        "_cache",
    }
)


@pytest.mark.asyncio
async def test_no_handler_world_or_module_object_retains_a_request_scope() -> None:
    """The realistic regression: a future contributor re-adds a cached field.

    Review does not reliably catch that, so it is asserted structurally: the handler declares no
    scope-shaped slot and holds no scope value after a request, the world holds no scope object,
    and the connector module holds none either.
    """
    import screamingface_engine.world.connector as connector_module

    gw = _MockAigateway((MODEL,))
    cfg = AigatewayConfig(models=gw.models, default_model=MODEL)
    scope = RequestScope(
        origin="run",
        identity_headers={"X-User-Email": "a@x.test"},
        profile="profile-a",
        answer_seed=44,
    )

    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        with request_scope(scope):
            await url4_run(f"/{MODEL}('ctx')!'go'", io=world.node)

        assert set(_ModelEndpoint.__slots__).isdisjoint(_SCOPE_FIELD_NAMES)

        handler = cast(Any, world.node)._endpoints[f"/{MODEL}"]
        for slot in _ModelEndpoint.__slots__:
            value = getattr(handler, slot)
            assert value is not scope
            if isinstance(value, Mapping):
                assert "X-User-Email" not in value, "the request's identity map is cached on a slot"

        for value in vars(world).values():
            assert not isinstance(value, RequestScope)
        for value in vars(connector_module).values():
            assert not isinstance(value, RequestScope)


# --- T6 / AC6: the child boot binds the scope from its environment ----------------------------


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


def test_the_child_boot_producer_reads_the_scope_from_the_job_env() -> None:
    env = {
        **job_env.identity_to_env({"X-User-Email": "run@x.test"}),
        job_env.AIGATEWAY_PROFILE: "prof",
        job_env.ANSWER_SEED: "7",
        job_env.CACHE_PARTICIPATE: "false",
        job_env.CACHE_MAX_AGE_S: "60",
    }

    scope = request_scope_from_env(env)

    assert scope.identity_headers == {"X-User-Email": "run@x.test"}
    assert scope.profile == "prof"
    assert scope.answer_seed == 7
    assert scope.cache.participate is False
    assert scope.cache.max_age == 60
    assert scope.origin == "run"


def test_a_malformed_seed_keeps_the_child_boots_existing_error() -> None:
    with pytest.raises(RunnerConfigError, match=job_env.ANSWER_SEED):
        request_scope_from_env({job_env.ANSWER_SEED: "lucky"})


@pytest.mark.asyncio
async def test_a_malformed_seed_fails_the_run_not_the_scheduler() -> None:
    """AC1: the producer is LAZY, exactly as the world factory is.

    Building the executor must not raise — a raise here would take down the scheduling caller
    with nothing on the stream (`InProcessJobRunner.schedule`'s comment). The refusal belongs
    inside the run, where it becomes a Terminated(failed) frame like every other run failure.
    """
    executor = build_executor({job_env.ANSWER_SEED: "lucky"}, _declared())

    with pytest.raises(RunnerConfigError, match=job_env.ANSWER_SEED):
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'"):
            pass


@pytest.mark.asyncio
async def test_the_child_boots_producer_is_what_the_run_path_binds() -> None:
    """End to end: the env identity reaches aigateway through the bound scope, not the world."""
    gw = _MockAigateway((MODEL,))
    env = {
        **job_env.identity_to_env({"X-User-Email": "run@x.test"}),
        job_env.AIGATEWAY_PROFILE: "prof",
    }

    async with gw.client() as client:
        executor = build_executor(env, _declared(), client=client)
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'"):
            pass

    assert gw.requests[0].headers["X-User-Email"] == "run@x.test"
    assert gw.requests[0].headers["X-Profile"] == "prof"


# --- FX-1 (04-review-fixes §2.1): the request deadline -------------------------------------


def test_a_scope_has_no_deadline_by_default() -> None:
    """The run producer binds no deadline, so the ensemble path's retry is unchanged."""
    assert RequestScope(origin="run").deadline is None
    assert request_scope_from_env({}).deadline is None


def test_the_sync_producer_carries_the_deadline_it_is_given() -> None:
    from screamingface_engine.request_scope import request_scope_from_headers

    assert request_scope_from_headers({}).deadline is None
    assert request_scope_from_headers({}, deadline=123.5).deadline == 123.5
