"""FX-62 — a fan-out's model calls carry their OWN run's identity, under concurrent runs.

# WHY this file exists. AC4 says a spawned model call inherits the scope of the task that created
# it, and AC2 says sibling requests never share one. The existing tests prove each half alone
# (one run's fan-out; two single calls). A url4 fan-out spawns its branches as tasks INSIDE the
# engine, so the case that can actually leak is both at once: two runs, each fanning out, with
# every branch in flight at the same moment (U1-M5).
#
# The stub gateway holds each fan-out branch on a four-party barrier, so the test passes only if
# all four branch calls (two per run) are really in flight together. A barrier that never fills
# fails the test on a timeout rather than letting a serialised run pass by accident. Every call
# is attributed to its run by its CONTENT, never by the header under test.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import build_world

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

MODEL = "anthropic/claude-haiku-4-5"
_RUNS = ("a", "b")
_BRANCHES = ("1", "2")
_OVERLAP_TIMEOUT_S = 5.0


def _fan_out(run: str) -> str:
    """Two model calls fanned out, then one reduce call on the default route. Every context
    names its run, so each outbound call can be attributed to a run by its CONTENT alone."""
    return f"(/{MODEL}('{run}-1')!'x', /{MODEL}('{run}-2')!'y')!'combine'"


def _identity(run: str) -> str:
    return f"run-{run}@x.test"


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL, web_search=False),),
        )
    )


def _user_content(request: httpx.Request) -> str:
    return json.loads(request.content)["messages"][-1]["content"]


class _OverlappingGateway:
    """A stub aigateway that answers a fan-out branch only once every branch has arrived.

    A branch answers ``answer:<its context>``, so the reduce call's input names its run too.
    """

    def __init__(self) -> None:
        self.branches = frozenset(f"{run}-{branch}" for run in _RUNS for branch in _BRANCHES)
        self.barrier = asyncio.Barrier(len(self.branches))
        self.calls: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        content = _user_content(request)
        if content in self.branches:
            async with asyncio.timeout(_OVERLAP_TIMEOUT_S):
                await self.barrier.wait()
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": f"answer:{content}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )


def _run_of(request: httpx.Request) -> str:
    """The run a call belongs to, read from its content: a branch's own context, or the branch
    answers url4 folds into the reduce call's prompt."""
    content = _user_content(request)
    prompt = "\n".join(m["content"] for m in json.loads(request.content)["messages"])
    (run,) = [run for run in _RUNS if content.startswith(f"{run}-") or f"answer:{run}-" in prompt]
    return run


async def _run(run: str, client: httpx.AsyncClient) -> None:
    env = {
        **job_env.identity_to_env({"X-User-Email": _identity(run)}),
        job_env.AIGATEWAY_PROFILE: f"profile-{run}",
    }
    executor = build_executor(env, _config(), client=client)
    async for _ in executor.execute(_fan_out(run)):
        pass


async def test_every_fan_out_call_carries_its_own_runs_identity_under_concurrent_runs() -> None:
    gateway = _OverlappingGateway()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        await asyncio.gather(*(_run(run, client) for run in _RUNS))

    chats = [r for r in gateway.calls if r.url.path == "/v1/chat/completions"]
    # Two branches and one reduce per run. Reaching here means the barrier filled: all four
    # branch calls were in flight together.
    assert len(chats) == len(_RUNS) * (len(_BRANCHES) + 1), [_user_content(r) for r in chats]
    for request in chats:
        run = _run_of(request)
        assert request.headers["X-User-Email"] == _identity(run), _user_content(request)
        assert request.headers["X-Profile"] == f"profile-{run}", _user_content(request)


async def _run_on_shared(run: str, shared: object) -> None:
    """Same run body as ``_run``, but on the SHARED world (the local-mode shape, item 9)."""
    env = {
        **job_env.identity_to_env({"X-User-Email": _identity(run)}),
        job_env.AIGATEWAY_PROFILE: f"profile-{run}",
    }
    executor = build_executor(env, io_provider=lambda: shared)
    async for _ in executor.execute(_fan_out(run)):
        pass


async def test_every_fan_out_call_carries_its_own_runs_identity_on_one_shared_world() -> None:
    """The local-mode shape (C8): ONE handler/world serves BOTH runs' fan-out, concurrently.

    Every other test in this module (and `test_run_path_fixes.py`'s shared-world cases) drives
    at most one run at a time through a shared world, or two runs through TWO separate worlds.
    Neither proves the handler stays stateless under concurrent fan-out on the SAME instance —
    exactly the shape `local.py`'s one node serving every in-process run takes.
    """
    gateway = _OverlappingGateway()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    ) as client:
        shared, aclose = await build_world(env={}, config=_config(), client=client)
        try:
            await asyncio.gather(*(_run_on_shared(run, shared) for run in _RUNS))
        finally:
            if aclose is not None:
                await aclose()

    chats = [r for r in gateway.calls if r.url.path == "/v1/chat/completions"]
    assert len(chats) == len(_RUNS) * (len(_BRANCHES) + 1), [_user_content(r) for r in chats]
    for request in chats:
        run = _run_of(request)
        assert request.headers["X-User-Email"] == _identity(run), _user_content(request)
        assert request.headers["X-Profile"] == f"profile-{run}", _user_content(request)
