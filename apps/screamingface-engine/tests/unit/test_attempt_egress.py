"""OME-1458 — Attempt 2 of a Case is never a copy of Attempt 1.

FEATURE: a Benchmark may ask each Case N times and mark a Check met if any Attempt met it. The
AI gateway's global cache keys on the exact request, so Attempt 2 — the identical request —
would be served Attempt 1's stored reply and the score would silently be first-Attempt only.
The Candidate Invocation of Attempt 2 and later carries an ``attempt`` param; inside it, every
model call sends either a seed derived from the run's answer seed (when the run's seed applies)
or the Attempt number in the gateway's cache control (otherwise).

STORY: Attempt 1 of "What is 6 times 7?" answers 41 and is stored. Attempt 2 sends
``cache: {"attempt": 2}`` in an unseeded run (or a derived seed in a seeded one), so the
gateway asks the model afresh, and a rerun replays both Attempts from the cache.

INVARIANT: Attempt 1 — every call of every Benchmark without Attempts — sends exactly the
request it sent before. A judge never carries an Attempt: grading is outside the Candidate
Invocation.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_answer_seed_threading import MODEL, _MockAigateway

from screamingface_engine.benchmarks.case_context import case_attempt_scope, current_case_attempt
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.cache import (
    attempt_body_field,
    policy_to_body_field,
    with_cache_policy,
)
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.request_parameters import attempt_egress, derive_attempt_seed
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.streaming.protocol import CachePolicy


def _candidate(attempt: str | None = None, *, inner_params: str = "") -> str:
    """One Candidate Invocation around one model call, as Attempt ``attempt`` (None = 1)."""

    inner = f"/{MODEL}('case-ctx')!'answer'{inner_params}"
    params: tuple[tuple[str, str], ...] = (("web_search", "false"),)
    if attempt is not None:
        params += (("attempt", attempt),)
    return render(
        expr(
            src(
                RelExpr(
                    path="/benchmarks/candidate",
                    context="case-ctx",
                    intent=text(inner),
                    params=params,
                ),
                name="answer",
                weight=0.0,
            ),
            intent=text("$answer"),
        )
    )


async def _bodies(
    expression: str, *, answer_seed: int | None = None, cache: CachePolicy | None = None
) -> list[dict[str, Any]]:
    """Every chat body the world sends while running ``expression`` under one run's scope."""

    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    scope = RequestScope(origin="run", answer_seed=answer_seed, cache=cache or CachePolicy())
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        install_candidate_invocation(world.node)
        with request_scope(scope):
            await url4_run(expression, io=world.node)
    return gw.bodies


# --- the decision, as a pure function ---------------------------------------------------


def test_attempt_one_changes_nothing() -> None:
    egress = attempt_egress({}, "7", None)

    assert (egress.answer_seed, egress.cache_attempt) == ("7", None)
    assert attempt_egress({}, None, None).cache_attempt is None


def test_a_seeded_attempt_two_gets_a_derived_seed_and_no_cache_attempt() -> None:
    egress = attempt_egress({}, "7", 2)

    assert egress.answer_seed == derive_attempt_seed("7", 2)
    assert egress.cache_attempt is None


def test_an_unseeded_attempt_two_names_itself_to_the_cache() -> None:
    egress = attempt_egress({}, None, 2)

    assert (egress.answer_seed, egress.cache_attempt) == (None, 2)


def test_a_self_seeded_call_names_its_attempt_to_the_cache() -> None:
    # WHY: a call pinning its own seed keeps it (the run's seed never overrides it), so
    # Attempt 2 would send Attempt 1's seed and be served Attempt 1's stored reply.
    egress = attempt_egress({"seed": "3"}, "7", 2)

    assert (egress.answer_seed, egress.cache_attempt) == ("7", 2)


def test_the_derived_seed_is_stable_and_differs_per_attempt() -> None:
    seeds: list[str] = [derive_attempt_seed("7", attempt) for attempt in (2, 3, 4)]

    assert seeds == [derive_attempt_seed("7", attempt) for attempt in (2, 3, 4)]
    assert len(set(seeds)) == 3
    assert "7" not in seeds
    assert derive_attempt_seed("7", 2) != derive_attempt_seed("8", 2)
    assert all(0 <= int(seed) < 2**31 for seed in seeds)


# --- the cache control ------------------------------------------------------------------


def test_attempt_one_adds_nothing_and_merges_exactly_as_before() -> None:
    body: dict[str, object] = {"model": MODEL, "messages": []}

    assert attempt_body_field(None) == {}
    for policy in (CachePolicy(), CachePolicy(participate=False)):
        assert with_cache_policy(body, policy) == {**body, **policy_to_body_field(policy)}


def test_the_policy_joins_an_attempt_inside_its_cache_object() -> None:
    body: dict[str, object] = {"model": MODEL, **attempt_body_field(2)}

    assert with_cache_policy(body, CachePolicy())["cache"] == {"attempt": 2}
    # The re-issue path builds its opt-out this way, so it keeps the Attempt too.
    assert with_cache_policy(body, CachePolicy(participate=False))["cache"] == {
        "attempt": 2,
        "use-cache": False,
    }


# --- the Attempt scope ------------------------------------------------------------------


def test_no_attempt_scope_means_no_attempt() -> None:
    assert current_case_attempt() is None


def test_the_attempt_scope_holds_its_number_and_closes() -> None:
    with case_attempt_scope(3):
        assert current_case_attempt() == 3
    assert current_case_attempt() is None


@pytest.mark.parametrize("attempt", [1, 0, True])
def test_attempt_one_or_garbage_cannot_open_a_scope(attempt: Any) -> None:
    with pytest.raises(ValueError), case_attempt_scope(attempt):
        pass


# --- through the world: what the gateway receives ---------------------------------------


@pytest.mark.asyncio
async def test_attempt_one_sends_todays_request_byte_for_byte() -> None:
    unseeded: list[dict[str, Any]] = await _bodies(_candidate())
    seeded: list[dict[str, Any]] = await _bodies(_candidate(), answer_seed=7)

    assert [set(body) for body in unseeded] == [{"model", "messages"}]
    assert [body["seed"] for body in seeded] == [7]
    assert "cache" not in seeded[0]


@pytest.mark.asyncio
async def test_an_unseeded_attempt_two_carries_its_number_in_the_cache_control_only() -> None:
    bodies: list[dict[str, Any]] = await _bodies(_candidate("2"))

    assert bodies[0]["cache"] == {"attempt": 2}
    assert set(bodies[0]) == {"model", "messages", "cache"}
    assert bodies[0]["messages"][-1]["content"] == "case-ctx"


@pytest.mark.asyncio
async def test_a_seeded_attempt_two_carries_a_derived_seed_and_no_cache_attempt() -> None:
    bodies: list[dict[str, Any]] = await _bodies(_candidate("2"), answer_seed=7)

    assert bodies[0]["seed"] == int(derive_attempt_seed("7", 2))
    assert "cache" not in bodies[0]


@pytest.mark.asyncio
async def test_a_self_seeded_candidate_attempt_two_carries_the_cache_attempt() -> None:
    bodies: list[dict[str, Any]] = await _bodies(
        _candidate("2", inner_params=";seed=3"), answer_seed=7
    )

    assert bodies[0]["seed"] == 3
    assert bodies[0]["cache"] == {"attempt": 2}


@pytest.mark.asyncio
async def test_an_opted_out_run_keeps_its_opt_out_beside_the_attempt() -> None:
    bodies: list[dict[str, Any]] = await _bodies(
        _candidate("2"), cache=CachePolicy(participate=False)
    )

    assert bodies[0]["cache"] == {"use-cache": False, "attempt": 2}


@pytest.mark.asyncio
async def test_a_judge_call_never_carries_the_attempt() -> None:
    # WHY: grading runs outside the Candidate Invocation. Even inside an Attempt scope, a model
    # call that is not answering the Case keeps today's request, so a Judge grading the same
    # answer twice is served the same stored verdict.
    with case_attempt_scope(2):
        bodies: list[dict[str, Any]] = await _bodies(f"/{MODEL}('grade this')!'verdict'")

    assert "cache" not in bodies[0]
    assert "seed" not in bodies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", ["1", "0", "two", "-2"])
async def test_a_malformed_attempt_param_is_a_contract_error(attempt: str) -> None:
    with pytest.raises(ResolutionError, match="attempt"):
        await _bodies(_candidate(attempt))


@pytest.mark.asyncio
async def test_the_attempt_param_is_not_a_retrieval_policy_param() -> None:
    # WHY: the adapter refuses any unknown policy param; `attempt` is call metadata, stripped
    # before the policy check, so it must not trip `candidate_policy_invalid`.
    bodies: list[dict[str, Any]] = await _bodies(_candidate("3"))

    assert bodies[0]["cache"] == {"attempt": 3}
