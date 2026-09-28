"""Golden parity for the run path (prd/01 T5, AC1).

# WHY this file exists. Unit 1 moves ``build_aigateway_world`` and the ``_world()`` factory out of
# ``runner/`` and replaces the per-run fields on ``_ModelEndpoint`` with a ``request_scope``
# ContextVar. That refactor is only "behaviour-preserving" if an EXACT run — fixed expression,
# fixed answer seed, fixed cache policy, fixed stub — produces the byte-identical result and the
# byte-identical outbound request afterwards. This test records both, on the PRE-refactor tree,
# so a later diff that changes either fails here instead of in production.
#
# # INVARIANT (T5): the recorded values are pre-refactor behaviour, not aspirations. They were
# captured from the real production path (``runner.main.build_executor`` and the ``_world()``
# factory it closes over), against the shared connector stub. Do not regenerate them to make a
# refactor pass: a changed value here IS the behaviour change the plan forbids.
#
# The answer seed is observable on the wire only inside a Candidate invocation (the answering
# boundary, OME-1038), so the fixed expression routes through ``/benchmarks/candidate``. The seed
# on the body is therefore part of the golden, not incidental.
"""

from __future__ import annotations

import json

import pytest
from test_aigateway_connector import _MockAigateway

from screamingface_engine import job_env
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from url4.streaming.interfaces import Completed

pytestmark = pytest.mark.asyncio

MODEL = "anthropic/claude-haiku-4-5"

# A rendered Candidate expression, frozen as a literal so the golden cannot drift if a test
# helper changes. Produced once by url4's own renderer; `<MODEL>` below is the model id above.
_GOLDEN_EXPRESSION = (
    "(answer:0.0:/benchmarks/candidate?web_search=false&q=(case-ctx)!'"
    "/anthropic/claude-haiku-4-5(\\'case-ctx\\')!\\'answer\\'')!'$answer'"
)

_GOLDEN_ANSWER = "golden answer"

# The exact chat-completions body aigateway observed. `cache` is present because the run opted
# out; `seed` is present because the call is an ANSWER call, not a benchmark-authored judge call.
_GOLDEN_REQUEST = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "answer"},
        {"role": "user", "content": "case-ctx"},
    ],
    "cache": {"use-cache": False},
    "seed": 7,
}

_GOLDEN_RESULT = (
    '{"schema":"screamingface.candidate-invocation.v1","status":"completed",'
    '"output":"golden answer","finish_reason":null,"refusal":null,"execution":null}'
)


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=MODEL,
            models=(ModelSpec(id=MODEL, web_search=False),),
        )
    )


def _env() -> dict[str, str]:
    """The run's per-run env: one cache opt-out and one declared sitting."""
    return {job_env.CACHE_PARTICIPATE: "false", job_env.ANSWER_SEED: "7"}


async def _drain(executor: object) -> str:
    """Run the executor to completion and return the inline result body."""
    completed: Completed | None = None
    async for step in executor.execute(_GOLDEN_EXPRESSION):  # type: ignore[attr-defined]
        if isinstance(step, Completed):
            completed = step
    assert completed is not None, "the run produced no Completed frame"
    assert completed.result.body is not None, "the result spilled instead of staying inline"
    return completed.result.body


async def test_the_run_path_produces_its_recorded_result_and_request() -> None:
    gw = _MockAigateway((MODEL,), responses={MODEL: _GOLDEN_ANSWER}, web_search=False)

    async with gw.client() as client:
        executor = build_executor(_env(), _config(), client=client, benchmarks=BUILTIN_BENCHMARKS)
        result = await _drain(executor)

    chats = [r for r in gw.requests if r.url.path == "/v1/chat/completions"]
    assert len(chats) == 1, "the golden run must make exactly one aigateway call"
    request = json.loads(chats[0].content)

    assert request == _GOLDEN_REQUEST
    assert result == _GOLDEN_RESULT


# --- FX-63 (U1-M6): the same golden run, with an identity and a profile ---------------------------

# The caller-state headers aigateway observed, recorded on `main` (pre-refactor tree) with the env
# below. Every OTHER header on the call is httpx's own, so the engine-owned subset is exactly these
# two: no traceparent (this drive binds no run trace) and no second identity header.
_GOLDEN_IDENTITY_HEADERS = {"x-profile": "golden-profile", "x-user-email": "golden@x.test"}
_HTTPX_OWN_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "connection",
        "content-length",
        "content-type",
        "host",
        "user-agent",
    }
)


def _identity_env() -> dict[str, str]:
    """The golden env plus the caller state the ensemble path forwards: identity and profile."""
    return {
        **_env(),
        **job_env.identity_to_env({"X-User-Email": "golden@x.test"}),
        job_env.AIGATEWAY_PROFILE: "golden-profile",
    }


async def test_the_run_path_with_identity_and_profile_sends_its_recorded_headers_and_body() -> None:
    gw = _MockAigateway((MODEL,), responses={MODEL: _GOLDEN_ANSWER}, web_search=False)

    async with gw.client() as client:
        executor = build_executor(
            _identity_env(), _config(), client=client, benchmarks=BUILTIN_BENCHMARKS
        )
        result = await _drain(executor)

    chats = [r for r in gw.requests if r.url.path == "/v1/chat/completions"]
    assert len(chats) == 1, "the golden run must make exactly one aigateway call"
    sent = {name.lower(): value for name, value in chats[0].headers.items()}
    engine_owned = {name: value for name, value in sent.items() if name not in _HTTPX_OWN_HEADERS}

    assert engine_owned == _GOLDEN_IDENTITY_HEADERS
    assert json.loads(chats[0].content) == _GOLDEN_REQUEST
    assert result == _GOLDEN_RESULT
