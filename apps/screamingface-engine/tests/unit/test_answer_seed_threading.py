"""OME-1038 — a run's declared answer seed travels from the REST edge onto every answer call.

FEATURE: answer seeds (OME-1038). A leaderboard score today is one exam sitting presented
as the student's ability. Declaring an answer seed names the sitting: N runs with N seeds
are N labelled, cache-separated samples, so a score can be published as mean ± CI and any
sitting replayed exactly. The seed makes the same journey `profile` and the cache policy
already make:

    GET / (X-Answer-Seed) ──► _schedule ──► JobRunner.schedule(answer_seed=…) ──► the run's
    ENV ──► build_executor ──► the connector merges `seed` into the call's params ──► body

INVARIANT: absence is the default. A run that declares nothing renders egress bodies
byte-identical to today's — which is what keeps every recorded replay fixture valid, the
whole reason this shipped as an ambient per-run value and not a template change.

INVARIANT: an explicit `seed` param on a call always wins over the run's ambient seed.
The draco judge stamps one stable seed per pass for independent cache slots; an ambient
seed overwriting those would silently re-key the judge cache and change grading identity.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.request_parameters import apply_answer_seed
from url4.dag import run as url4_run
from url4.io.layer import IOLayer
from url4.streaming.protocol import CachePolicy

SECRET = "answer-seed-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
# A PAST instant on purpose: pyjwt validates `iat` against the real clock, so a T0 ahead of
# the wall clock makes every minted token "from the future" and each request a 401.
T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
MODEL = "anthropic/claude-haiku-4-5"


# --- the param merge: the one rule that protects the judge ------------------------------------


def test_no_declared_seed_leaves_the_params_untouched() -> None:
    """The byte-identity guarantee starts here: None must be a no-op, not a default."""
    params = {"temperature": "0.2"}

    assert apply_answer_seed(params, None) is params


def test_a_declared_seed_lands_on_a_call_that_states_none() -> None:
    merged = apply_answer_seed({"temperature": "0.2"}, "7")

    assert merged == {"temperature": "0.2", "seed": "7"}


def test_a_call_pinning_its_own_seed_wins_over_the_runs() -> None:
    """The judge protection: draco stamps `seed=1..N` per pass — never re-keyed ambiently."""
    params = {"seed": "3"}

    merged = apply_answer_seed(params, "7")

    assert merged["seed"] == "3"


# --- the contract sets: the seed is per-RUN, and it is not a secret ---------------------------


def test_the_answer_seed_env_name_is_per_run_and_never_deploy_time() -> None:
    assert job_env.ANSWER_SEED in job_env.WRITTEN_BY_APP
    assert job_env.ANSWER_SEED not in job_env.DEPLOY_TIME
    assert job_env.ANSWER_SEED not in job_env.SECRET


# --- the env round trip -----------------------------------------------------------------------


def test_a_declared_seed_round_trips_through_the_env() -> None:
    env = job_env.answer_seed_to_env(7)

    assert env == {job_env.ANSWER_SEED: "7"}
    assert job_env.answer_seed_from_env(env) == 7


def test_a_run_that_declared_nothing_writes_no_seed_variable_at_all() -> None:
    """Silence stays distinguishable from a stated seed all the way down."""
    assert job_env.answer_seed_to_env(None) == {}
    assert job_env.answer_seed_from_env({}) is None


def test_a_negative_seed_is_a_legal_seed() -> None:
    """aigateway's `seed` is an ARBITRARY integer (OME-585) — no range narrowing here."""
    assert job_env.answer_seed_from_env(job_env.answer_seed_to_env(-5)) == -5


def test_a_malformed_seed_refuses_the_run_rather_than_running_unseeded() -> None:
    """Of the two wrong answers, the loud one: a run silently executed WITHOUT its declared
    seed would publish a score claiming a sitting it never had — the exact dishonesty this
    feature exists to end. This env is App-written, so garbage is a bug, not caller input."""
    with pytest.raises(ValueError, match=job_env.ANSWER_SEED):
        job_env.answer_seed_from_env({job_env.ANSWER_SEED: "lucky"})


# --- the two renderings: the queue codec and the inprocess adapter ----------------------------


def test_the_queue_codec_carries_a_declared_seed() -> None:
    env = decode_message(encode_message("t", "gpt(hi)", 60, answer_seed=7))

    assert job_env.answer_seed_from_env(env) == 7


def test_the_queue_codec_renders_nothing_for_an_undeclared_seed() -> None:
    env = decode_message(encode_message("t", "gpt(hi)", 60))

    assert job_env.ANSWER_SEED not in env


class _NeverExecutor:
    """Never executed — these tests assert the env the runner BUILDS, not what it then runs."""

    async def execute(self, url4: str, *, trace: object | None = None) -> Any:
        raise NotImplementedError  # pragma: no cover


def _local_runner(base_env: dict[str, str] | None = None) -> InProcessJobRunner:
    return InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),  # type: ignore[arg-type,return-value]
        base_env=base_env,
    )


def test_this_runs_seed_replaces_any_ambient_one() -> None:
    """`_base_env` is shared by every local run — a leftover seed there would stamp one
    caller's sitting onto the next caller's run, corrupting BOTH records."""
    stale = {job_env.ANSWER_SEED: "99"}

    env = _local_runner(stale)._env(  # noqa: SLF001
        "t", "gpt(hi)", 60, None, None, None, None, answer_seed=7
    )

    assert job_env.answer_seed_from_env(env) == 7


def test_a_run_with_no_seed_clears_any_ambient_one() -> None:
    stale = {job_env.ANSWER_SEED: "99"}

    env = _local_runner(stale)._env(  # noqa: SLF001
        "t", "gpt(hi)", 60, None, None, None, None, answer_seed=None
    )

    assert job_env.ANSWER_SEED not in env


# --- the REST edge: the header reaches the job runner -----------------------------------------


class _SeedRecordingRunner(RecordingJobRunner):
    """`RecordingJobRunner`, plus the one argument this unit adds to the port.

    Recorded here rather than on the shared fake's `ScheduledRun` on purpose — that tuple is
    compared whole by an existing test, so widening it would change a committed assertion.
    """

    def __init__(self) -> None:
        super().__init__()
        self.answer_seeds: list[int | None] = []

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        client_version: str | None = None,
    ) -> str:
        self.answer_seeds.append(answer_seed)
        return await super().schedule(
            topic,
            url4,
            deadline_s,
            traceparent=traceparent,
            credential=credential,
            profile=profile,
            identity=identity,
        )


async def _start(runner: _SeedRecordingRunner, topic: str, **headers: str) -> httpx.Response:
    app: FastAPI = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=FixedGate(),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": JwtCodec(
                    secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S
                ).sign(topic, T0),
                "Prefer": "respond-async",
                **headers,
            },
        )


@pytest.mark.asyncio
async def test_the_answer_seed_header_reaches_the_job_runner() -> None:
    runner = _SeedRecordingRunner()

    resp = await _start(runner, "seed-declared", **{"X-Answer-Seed": "7"})

    assert resp.status_code == 202
    assert runner.answer_seeds == [7]


@pytest.mark.asyncio
async def test_a_run_without_the_header_schedules_no_seed() -> None:
    runner = _SeedRecordingRunner()

    await _start(runner, "seed-absent")

    assert runner.answer_seeds == [None]


@pytest.mark.asyncio
async def test_a_non_integer_answer_seed_is_a_400_problem() -> None:
    """Caller input, so refused at the edge — never scheduled, never silently dropped."""
    runner = _SeedRecordingRunner()

    resp = await _start(runner, "seed-garbage", **{"X-Answer-Seed": "lucky"})

    assert resp.status_code == 400
    assert runner.answer_seeds == []


# --- the run mode: the env reaches the connector ----------------------------------------------


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


class _MockAigateway:
    """Records every chat-completions body the world sends."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.contents: list[bytes] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.contents.append(request.content)
        self.bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


def _candidate_wrapped(inner_ctx: str = "case-ctx", *, inner_params: str = "") -> str:
    """One Candidate invocation around one model call — the shape every answer call has.

    WHY every seeded assertion runs through this (review round): the seed is an ANSWER
    seed — it exists only inside the Candidate invocation, so a bare model call is the
    judge's shape and must stay unseeded.
    """
    from url4 import RelExpr, expr, render, src, text

    # `;k=v` is the post-call param chain (the same form test_native_web_search uses) —
    # the only way to pin a param in hand-written url4 without fighting nested quoting.
    inner = f"/{MODEL}('{inner_ctx}')!'answer'{inner_params}"
    return render(
        expr(
            src(
                RelExpr(
                    path="/benchmarks/candidate",
                    context=inner_ctx,
                    intent=text(inner),
                    params=(("web_search", "false"),),
                ),
                name="answer",
                weight=0.0,
            ),
            intent=text("$answer"),
        )
    )


@pytest.mark.asyncio
async def test_the_runs_env_reaches_the_connectors_request_body() -> None:
    """The one hop no unit below this can prove: `build_executor` reading the seed back."""
    from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS

    gw = _MockAigateway()
    env = job_env.answer_seed_to_env(7)

    async with gw.client() as client:
        # The builtin registry is what installs the Candidate adapter, exactly as the run
        # mode does — the seed only ever applies inside a Candidate invocation.
        executor = build_executor(env, _declared(), client=client, benchmarks=BUILTIN_BENCHMARKS)
        async for _ in executor.execute(_candidate_wrapped()):
            pass

    # `model_params` JSON-coerces "7" → 7, so the gateway sees the integer form OME-585 admits.
    assert gw.bodies[0]["seed"] == 7


# --- egress: what the gateway actually receives -----------------------------------------------


async def _bodies(answer_seed: int | None, *, expression: str | None = None) -> _MockAigateway:
    from screamingface_engine.world.candidate_adapter import install_candidate_invocation

    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        # F2: the seed is per-REQUEST now — it travels in the scope, not on the world.
        with request_scope(RequestScope(origin="run", answer_seed=answer_seed)):
            await url4_run(expression or _candidate_wrapped(), io=world.node)
    return gw


@pytest.mark.asyncio
async def test_an_undeclared_runs_body_is_byte_identical_to_todays() -> None:
    """THE acceptance criterion: turning this feature on changes nothing about an ordinary
    run's request — which is what keeps every recorded replay fixture (request-keyed) valid."""
    unseeded = await _bodies(None)

    assert all(set(body) == {"model", "messages"} for body in unseeded.bodies)


@pytest.mark.asyncio
async def test_a_declared_seed_reaches_every_answer_call() -> None:
    gw = await _bodies(7)

    assert gw.bodies[0]["seed"] == 7
    assert set(gw.bodies[0]) == {"model", "messages", "seed"}
    assert gw.bodies[0]["messages"][-1]["content"] == "case-ctx"


@pytest.mark.asyncio
async def test_the_same_seed_produces_byte_identical_requests() -> None:
    """Reproducibility, stated as bytes: same seed, same cases ⇒ the same cache slot."""
    first = await _bodies(7)
    second = await _bodies(7)

    assert first.contents == second.contents


@pytest.mark.asyncio
async def test_different_seeds_produce_different_requests() -> None:
    """Two sittings must be two cache slots, or N passes silently collapse into one sample."""
    first = await _bodies(1)
    second = await _bodies(2)

    assert first.contents != second.contents


@pytest.mark.asyncio
async def test_a_call_stating_its_own_seed_is_never_rekeyed_by_the_run() -> None:
    """End-to-end form of the judge protection: the expression's own `seed` param survives."""
    gw = await _bodies(7, expression=_candidate_wrapped(inner_params=";seed=3"))

    assert gw.bodies[0]["seed"] == 3


@pytest.mark.asyncio
async def test_two_concurrent_runs_with_different_seeds_do_not_contaminate_each_other() -> None:
    """All three worlds share ONE `AigatewayConfig` — the placement the design forbids.

    A seed parked on the shared world config would stamp one researcher's sitting onto
    another's concurrent run, corrupting BOTH records — and in local mode concurrent runs
    share one event loop, so the hazard is not hypothetical. The per-run endpoint field is
    what this test pins, exactly as the cache policy's twin test pins `_cache`.
    """
    gw = _MockAigateway()
    shared_cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)

    from screamingface_engine.world.candidate_adapter import install_candidate_invocation

    async def _seeded(seed: int | None, node: IOLayer, context: str) -> None:
        # Each run binds its own scope: this is what F2 gives the concurrency guarantee on.
        with request_scope(RequestScope(origin="run", answer_seed=seed)):
            await url4_run(_candidate_wrapped(context), io=node)

    async with gw.client() as client:
        first = await build_aigateway_world(shared_cfg, client=client)
        second = await build_aigateway_world(shared_cfg, client=client)
        unseeded = await build_aigateway_world(shared_cfg, client=client)
        for world in (first, second, unseeded):
            install_candidate_invocation(world.node)

        await asyncio.gather(
            _seeded(1, first.node, "run-a"),
            _seeded(2, second.node, "run-b"),
            _seeded(None, unseeded.node, "run-c"),
        )

    by_context = {body["messages"][-1]["content"]: body for body in gw.bodies}
    assert by_context["run-a"]["seed"] == 1
    assert by_context["run-b"]["seed"] == 2
    assert "seed" not in by_context["run-c"]


# --- the review round: the seed is an ANSWER seed, never a judge seed -------------------------


@pytest.mark.asyncio
async def test_the_seed_reaches_candidate_calls_and_never_judge_calls() -> None:
    """INVARIANT (review finding): grading identity never varies with the answer seed.

    HealthBench and GDPVal judges carry pinned params WITH NO seed — an ambient seed
    stamped onto them would re-key every judge call per sitting under an unchanged
    benchmark revision. The seed therefore applies ONLY inside the Candidate invocation
    (the boundary between caller-authored answering and benchmark-authored grading);
    a benchmark-authored call outside it must render byte-identically, seeded run or not.
    """
    from screamingface_engine.world.candidate_adapter import install_candidate_invocation
    from url4 import RelExpr, expr, render, src, text

    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    inner_candidate = f"/{MODEL}('case-ctx')!'answer'"
    outer = render(
        expr(
            src(
                RelExpr(
                    path="/benchmarks/candidate",
                    context="case-ctx",
                    intent=text(inner_candidate),
                    params=(("web_search", "false"),),
                ),
                name="answer",
                weight=0.0,
            ),
            src(
                RelExpr(path=f"/{MODEL}", context="judge-ctx", intent=text("grade")),
                name="judge",
                weight=0.0,
            ),
            intent=text("$answer"),
        )
    )

    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        with request_scope(RequestScope(origin="run", answer_seed=7)):
            await url4_run(outer, io=world.node)

    by_context = {body["messages"][-1]["content"]: body for body in gw.bodies}
    assert by_context["case-ctx"]["seed"] == 7
    assert "seed" not in by_context["judge-ctx"]
