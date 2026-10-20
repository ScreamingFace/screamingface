"""sf.samples() meets the Engine: each call keeps its own seed (OME-1289, SM-1/4/9/10).

FEATURE: ``sf.samples(model, n)`` (SDK unit 6) builds N members of one model that differ only in an
integer ``seed`` param, so a vote over them counts N real answers.
STORY: as a researcher running a samples vote with a declared answer seed, I want the Engine to send
N requests that differ only in their own seed, and to fail loudly when a gateway rejects the seed.
INVARIANT defended: a call's own ``seed`` always wins over the run's ambient answer seed, including
``0``; and the data file under ``data/combine_contract/`` is what the SDK compiles (the SDK drift
guard keeps it byte-equal), so these tests run the real compiler output. SM-10 (a gateway that
rejects the seed fails the Case) grades through IFEval, a local inspect Task since OME-1527, so it
lives in ``inspect/test_combine_candidates_on_ifeval.py``.

Most tests here pin behavior that already exists (CHAR); they pass on their first run by design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_answer_seed_threading import _bodies, _candidate_wrapped

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.definition import candidate_invocation, inert_text
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import expr, render, src, text
from url4.dag import run as url4_run

_CANDIDATE = (
    (Path(__file__).parent / "data" / "combine_contract" / "samples_vote_candidate.url4")
    .read_text(encoding="utf-8")
    .removesuffix("\n")
)
_MEMBER = "prov/member-a"
_RUN_SEED = 7


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


class _Gateway:
    """Records every chat body; replies by the body's own seed, so the answer is order-free."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.contents: list[bytes] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.contents.append(request.content)
        body = json.loads(request.content)
        self.bodies.append(body)
        return _chat("The answer is 4" if body["seed"] <= 2 else "The answer is 5")


def _wrapped_candidate(candidate: str) -> str:
    """The candidate linked to one case input, the way a benchmark invokes it."""
    # WHY: the Candidate contract (spec 2026-10-20 R2) — the case input is the intent and the
    # Recipe is bound as `candidate` (its `$` kept literal), exactly as a linked run binds it.
    return render(
        expr(
            src(text(inert_text(candidate)), name="candidate", weight=0.0),
            src(
                candidate_invocation("what is 2 + 2?", web_search=False),
                name="answer",
                weight=0.0,
            ),
            intent=text("$answer"),
        )
    )


async def _run_samples_vote() -> tuple[_Gateway, str]:
    gateway = _Gateway()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handle), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_MEMBER, models=(ModelSpec(id=_MEMBER),)), client=client
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        with request_scope(RequestScope(origin="run", answer_seed=_RUN_SEED)):
            result = await url4_run(_wrapped_candidate(_CANDIDATE), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    return gateway, result


@pytest.mark.asyncio
async def test_call_seed_wins_over_run_seed_even_when_it_is_zero() -> None:
    """SM-1 CHAR: a falsy call seed must not read as "no seed" and take the run's seed."""
    gateway = await _bodies(7, expression=_candidate_wrapped(inner_params=";seed=0"))

    assert gateway.bodies[0]["seed"] == 0


@pytest.mark.asyncio
async def test_five_samples_send_five_requests_differing_only_in_seed() -> None:
    """SM-4 engine half (+ SM-D1): the run seed 7 never overrides the samples' seeds 0..4."""
    gateway, text_result = await _run_samples_vote()

    assert len(gateway.bodies) == 5
    assert sorted(body["seed"] for body in gateway.bodies) == [0, 1, 2, 3, 4]
    assert {body["temperature"] for body in gateway.bodies} == {0.7}
    without_seed = {
        json.dumps({k: v for k, v in b.items() if k != "seed"}, sort_keys=True)
        for b in gateway.bodies
    }
    assert len(without_seed) == 1
    # The vote over the five real answers: three say 4, two say 5.
    decoded = decode_candidate_invocation_record(text_result)
    assert decoded.output == "The answer is 4"
    assert decoded.operations is not None
    combine = {op.operation_id: op for op in decoded.operations}["op_synthesis_1"].combine
    assert combine is not None
    assert combine.tally is not None
    assert [(row.value, row.score) for row in combine.tally] == [("4", 3.0), ("5", 2.0)]


@pytest.mark.asyncio
async def test_samples_vote_replays_identically() -> None:
    """SM-9 engine half: the same run twice sends the same five requests and ends the same way.

    Members run concurrently, so the request ORDER is not pinned, only the multiset of bytes.
    """
    first, first_text = await _run_samples_vote()
    second, second_text = await _run_samples_vote()

    assert sorted(first.contents) == sorted(second.contents)
    assert first_text == second_text
