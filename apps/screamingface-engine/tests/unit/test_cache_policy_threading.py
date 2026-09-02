"""Batch 6 — the resolved cache policy travels from the REST edge onto the aigateway request.

Convergence (Batch 5) ends with ONE policy per run and hands it to `_schedule`. This is the rest
of the journey, and it is the same journey `profile` and the caller's identity already make:

    GET / ──► _schedule ──► JobRunner.schedule(cache=…) ──► the run's ENV ──► build_executor
                                                                                   │
                        the aigateway chat-completions body ◄── the connector ◄─────┘

**PER-RUN, and that is the whole design constraint.** The obvious shortcut — parking the policy on
`AigatewayConfig` — is wrong for a reason no test would otherwise catch: that dataclass is WORLD
config, one instance describing the gateway for every run in the process, so a per-run value on it
is a value one caller's run can read out of another's. In local mode (`InProcessJobRunner`) those
runs share an event loop, so the contamination is not hypothetical. Hence
`test_two_concurrent_runs_with_different_policies_do_not_contaminate_each_other`, which builds both
worlds from ONE `AigatewayConfig` instance on purpose.

**The egress assertions are correctness tests, not style ones (spec §1.0).** aigateway v2's cache
grammar is CLOSED to exactly one key, `use-cache`; any other key inside the `cache` object makes
the whole request BYPASS the cache — silently, with nothing raised anywhere, even alongside a
valid `use-cache: true`. So "the body carries at most that one key" is the guard that stops a cache
which never hits and never says why, and `max_age` — url4-internal, applied at read-back — must be
proven NOT to reach the wire.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
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
from screamingface_engine.runner.cache import policy_to_body_field
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world_config import AigatewaySection, ModelSpec, WorldConfig
from url4.dag import run as url4_run
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import CachePolicy

SECRET = "cache-threading-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)
MODEL = "anthropic/claude-haiku-4-5"
TAVILY_TOKEN = "tvly-threading"  # noqa: S105 - not a real credential

OPT_OUT = CachePolicy(participate=False)
OPT_IN = CachePolicy(participate=True)
BOUNDED = CachePolicy(participate=True, max_age=60)


# --- the contract sets: the policy is per-RUN, and it is not a secret --------------------------


def test_the_cache_env_names_are_per_run_and_never_deploy_time() -> None:
    """Helm cannot know a policy that does not exist until a caller states one.

    The membership is not decoration: `WRITTEN_BY_APP` is what
    `test_job_env_contract.test_every_variable_the_app_writes_is_one_the_runner_reads` checks the
    App's writes against, so a name missing here is a variable written into a Job that nothing
    reads — the failure direction that breaks silently.
    """
    names = {job_env.CACHE_PARTICIPATE, job_env.CACHE_MAX_AGE_S}

    assert names <= job_env.WRITTEN_BY_APP
    assert not (names & job_env.DEPLOY_TIME)
    assert not (names & job_env.SECRET), (
        "a cache directive authorizes nothing and reveals nothing — declaring it SECRET would "
        "force it through valueFrom.secretKeyRef and imply a confidentiality it does not have"
    )


# --- the env round trip: one contract, rendered by the App and read by the run mode ------------


def test_an_opted_out_policy_round_trips_through_the_env() -> None:
    env = job_env.cache_policy_to_env(OPT_OUT)

    assert job_env.cache_policy_from_env(env) == OPT_OUT


def test_a_freshness_bound_survives_the_env_round_trip() -> None:
    """`max_age` is url4-internal and applied at read-back, so it has to REACH the run mode."""
    env = job_env.cache_policy_to_env(BOUNDED)

    assert job_env.cache_policy_from_env(env) == BOUNDED


def test_a_run_that_declared_nothing_writes_no_cache_variables_at_all() -> None:
    """`None` is "this hop was told nothing" — it must not render as a stated policy."""
    assert job_env.cache_policy_to_env(None) == {}


def test_an_env_with_no_cache_declaration_reads_back_as_nothing_stated() -> None:
    """And "nothing stated" must reach the wire as participation WITHOUT re-deciding D1 here.

    The default belongs to convergence and nowhere else. The run mode gets that answer for free:
    an unstated policy translates to an absent `cache` field, which v2 reads as participate — so
    a Job scheduled by an older App, or by hand, behaves like every other one.
    """
    policy = job_env.cache_policy_from_env({})

    assert policy.participate is None
    assert policy.max_age is None
    assert policy_to_body_field(policy) == {}


def test_an_unreadable_participation_value_is_read_as_an_opt_out() -> None:
    """Conservative on purpose: the expensive silent failure is caching a run that refused.

    This env is App-written, so a value that is neither `true` nor `false` is a bug rather than
    caller input — and the cheap wrong answer (a missed hit) is the one to take.
    """
    policy = job_env.cache_policy_from_env({job_env.CACHE_PARTICIPATE: "yes"})

    assert policy.participate is False


def test_an_unreadable_freshness_bound_is_dropped_rather_than_failing_the_run() -> None:
    policy = job_env.cache_policy_from_env(
        {job_env.CACHE_PARTICIPATE: "true", job_env.CACHE_MAX_AGE_S: "soon"}
    )

    assert policy == OPT_IN


# --- the two renderings: the queue codec and the inprocess adapter --------------------------


def _codec_env_of(cache: CachePolicy | None) -> dict[str, str]:
    """The deployed rendering of the policy: the queue message's per-run env mapping."""
    return decode_message(encode_message("t", "gpt(hi)", 60, cache=cache))


def test_the_queue_codec_writes_the_policy_as_plain_env_and_the_run_reads_it_back() -> None:
    env = _codec_env_of(BOUNDED)

    assert job_env.cache_policy_from_env(env) == BOUNDED


class _NeverExecutor(Executor):
    """Never executed — these tests assert the env the runner BUILDS, not what it then runs."""

    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:  # pragma: no cover - the run is never started
        raise NotImplementedError
        yield  # pragma: no cover - unreachable; makes this an async generator


def _local_runner(base_env: dict[str, str] | None = None) -> InProcessJobRunner:
    return InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        base_env=base_env,
    )


def test_the_inprocess_adapter_renders_the_same_env_as_the_queue_codec() -> None:
    """Local mode must not diverge: `build_executor` cannot tell a local run from a worker's.

    The one deliberate difference is `IO_CONCURRENCY` (the deployed worker writes the budget
    by env; local mode pops it in favour of the fair-share gate), so the comparison adds it
    back.
    """
    codec = _codec_env_of(OPT_OUT)

    local = _local_runner()._env("t", "gpt(hi)", 60, None, None, None, OPT_OUT)  # noqa: SLF001

    assert job_env.cache_policy_to_env(OPT_OUT).items() <= local.items()
    assert job_env.cache_policy_from_env(local) == job_env.cache_policy_from_env(codec)


def test_this_runs_policy_replaces_any_ambient_one() -> None:
    """`_base_env` is the App's OWN environment, shared by every local run.

    A leftover there would apply one caller's opt-out to the next caller's run — or, worse in the
    other direction, let a run that opted out inherit `participate=true` and be served a shared
    answer it explicitly refused.
    """
    stale = {job_env.CACHE_PARTICIPATE: "true", job_env.CACHE_MAX_AGE_S: "900"}

    env = _local_runner(stale)._env("t", "gpt(hi)", 60, None, None, None, OPT_OUT)  # noqa: SLF001

    assert job_env.cache_policy_from_env(env) == OPT_OUT


def test_a_run_with_no_policy_clears_any_ambient_one() -> None:
    stale = {job_env.CACHE_PARTICIPATE: "false"}

    env = _local_runner(stale)._env("t", "gpt(hi)", 60, None, None, None, None)  # noqa: SLF001

    assert job_env.cache_policy_from_env(env).participate is None


# --- the REST edge: the resolved policy reaches the job runner ---------------------------------


class _CacheRecordingRunner(RecordingJobRunner):
    """`RecordingJobRunner`, plus the one argument this batch adds to the port.

    Recorded here rather than in the shared fake's `ScheduledRun` on purpose: that tuple is
    compared whole by an earlier test, so widening it would change what a committed assertion
    means. A subclass adds the observation without touching anything already asserted.
    """

    def __init__(self) -> None:
        super().__init__()
        self.cache_policies: list[CachePolicy | None] = []

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
    ) -> str:
        self.cache_policies.append(cache)
        return await super().schedule(
            topic,
            url4,
            deadline_s,
            traceparent=traceparent,
            credential=credential,
            profile=profile,
            identity=identity,
        )


async def _start(runner: _CacheRecordingRunner, topic: str, **headers: str) -> httpx.Response:
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
async def test_the_headers_opt_out_reaches_the_job_runner() -> None:
    runner = _CacheRecordingRunner()

    resp = await _start(runner, "thread-no-store", **{"Cache-Control": "no-store"})

    assert resp.status_code == 202
    assert runner.cache_policies == [OPT_OUT]


@pytest.mark.asyncio
async def test_a_run_declaring_nothing_reaches_the_job_runner_already_resolved() -> None:
    """Never `None` past convergence — the runner must not be left to guess what silence meant."""
    runner = _CacheRecordingRunner()

    await _start(runner, "thread-default")

    assert runner.cache_policies == [OPT_IN]


# --- the run mode: the env reaches the connector ------------------------------------------------


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL),),
        )
    )


class _MockAigateway:
    """Records every chat-completions body, and can answer a scripted sequence per model."""

    def __init__(self, script: list[dict[str, Any] | str] | None = None) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.contents: list[bytes] = []
        self._script = script or []
        self._index = 0

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.contents.append(request.content)
        self.bodies.append(json.loads(request.content))
        if self._index < len(self._script):
            scripted = self._script[self._index]
            self._index += 1
            if isinstance(scripted, dict):
                return httpx.Response(200, json=scripted)
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


@pytest.mark.asyncio
async def test_the_runs_env_reaches_the_connectors_request_body() -> None:
    """The one hop no unit below this can prove: `build_executor` reading the policy back."""
    gw = _MockAigateway()
    env = job_env.cache_policy_to_env(OPT_OUT)

    async with gw.client() as client:
        executor = build_executor(env, _declared(), client=client)
        async for _ in executor.execute(f"/{MODEL}(ctx)!go"):
            pass

    assert gw.bodies[0]["cache"] == {"use-cache": False}


@pytest.mark.asyncio
async def test_an_env_that_declares_no_policy_sends_no_cache_field() -> None:
    gw = _MockAigateway()

    async with gw.client() as client:
        executor = build_executor({}, _declared(), client=client)
        async for _ in executor.execute(f"/{MODEL}(ctx)!go"):
            pass

    assert "cache" not in gw.bodies[0]


# --- egress: what the gateway actually receives -------------------------------------------------


async def _bodies(cache: CachePolicy | None, *, expression: str = f"/{MODEL}('ctx')!'go'") -> Any:
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client, cache=cache)
        await url4_run(expression, io=world.node)
    return gw


@pytest.mark.asyncio
async def test_a_default_runs_body_is_byte_identical_to_one_that_states_no_policy() -> None:
    """v2 reads absent, `null` and `{}` identically, so participation is expressed by SILENCE.

    Byte-compared rather than key-compared: the acceptance criterion is that turning this feature
    on changes nothing about an ordinary run's request, and `{"cache": {"use-cache": true}}` would
    satisfy a key-set assertion while enlarging the surface exposed to the closed-grammar bypass
    for no gain at all.
    """
    unstated = await _bodies(None)
    participating = await _bodies(OPT_IN)

    assert participating.contents == unstated.contents
    assert set(unstated.bodies[0]) == {"model", "messages"}


@pytest.mark.asyncio
async def test_an_opted_out_run_sends_use_cache_false_and_nothing_else() -> None:
    gw = await _bodies(OPT_OUT)

    body = gw.bodies[0]
    assert body["cache"] == {"use-cache": False}
    assert set(body) == {"model", "messages", "cache"}


@pytest.mark.asyncio
async def test_a_freshness_bound_never_reaches_the_wire() -> None:
    """D11 is applied at read-back. Sent as a control key it would BYPASS, which is the opposite.

    `max-age` is not in v2's grammar, and v2 does not ignore what it does not know — an extra key
    costs the caller every hit, for a bound the gateway was never going to honour anyway.
    """
    gw = await _bodies(BOUNDED)

    assert "cache" not in gw.bodies[0]
    assert set(gw.bodies[0]) == {"model", "messages"}


@pytest.mark.asyncio
async def test_no_policy_ever_puts_a_key_other_than_use_cache_on_the_wire() -> None:
    """The single most important regression guard here: an extra key is a silent, permanent cost."""
    for policy in (None, OPT_IN, OPT_OUT, BOUNDED, CachePolicy(), CachePolicy(max_age=0)):
        gw = await _bodies(policy)

        assert set(gw.bodies[0].get("cache", {})) <= {"use-cache"}, policy


@pytest.mark.asyncio
async def test_two_concurrent_runs_with_different_policies_do_not_contaminate_each_other() -> None:
    """Both worlds are built from ONE `AigatewayConfig` — the placement the plan forbids.

    Parked there, the second `build_aigateway_world` would rewrite the first run's policy, and in
    local mode the two runs share an event loop, so the winner would be whichever ran last.
    """
    gw = _MockAigateway()
    shared_cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)

    async with gw.client() as client:
        opted_out = await build_aigateway_world(shared_cfg, client=client, cache=OPT_OUT)
        participating = await build_aigateway_world(shared_cfg, client=client, cache=OPT_IN)

        await asyncio.gather(
            url4_run(f"/{MODEL}('run-a')!'go'", io=opted_out.node),
            url4_run(f"/{MODEL}('run-b')!'go'", io=participating.node),
        )

    by_context = {body["messages"][-1]["content"]: body for body in gw.bodies}
    assert by_context["run-a"]["cache"] == {"use-cache": False}
    assert "cache" not in by_context["run-b"]


def _tool_call_turn() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "who is leo"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.mark.asyncio
async def test_the_tool_calling_loop_applies_the_policy_on_every_round_trip() -> None:
    """One url4 turn is several gateway calls, and each is keyed and cached independently.

    A policy that lapsed after the first would be worse than none: the caller who asked for a
    fresh answer would get one, then have the tool-augmented continuation — the expensive, most
    context-specific call of the turn — served from a shared corpus anyway.
    """
    gw = _MockAigateway(script=[_tool_call_turn()])
    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, json={"results": [{"title": "t", "url": "u"}]})
        ),
        base_url="https://api.tavily.com",
    )
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)

    async with gw.client() as client, tavily:
        world = await build_aigateway_world(
            cfg,
            client=client,
            cache=OPT_OUT,
            tavily_api_key=TAVILY_TOKEN,
            tavily_client=tavily,
        )
        await url4_run(f"/{MODEL}('ctx')!'go'", io=world.node)

    assert len(gw.bodies) == 2, "the tool loop must have made a second round trip"
    assert all(body["cache"] == {"use-cache": False} for body in gw.bodies)
