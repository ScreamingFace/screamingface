"""SDK-written quorum reducers run in the engine world (OME-1289 E4a unit 13 x OME-1557).

FEATURE: the url4 files ``quorum_vote_candidate.url4`` and ``quorum_judge_vote_candidate.url4`` are
what the SDK compiles for ``sf.Fusion([...], synthesizer=<reducer>, quorum=2)`` with an optional
third member (the SDK drift guard keeps them byte-equal). Each test runs that compiler output
through the mocked gateway and makes the optional member's provider fail.
STORY: as a researcher, the vote still answers when an optional member fails, the evidence names
that member ``missing``, and the judge scores only the members that answered.
INVARIANT defended: url4 enforces the quorum before the combine call; the combine call never sees
a failed member's text and never counts it as a vote.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping
from typing import Any

import httpx
import pytest
from _signal_world import _gateway, operation
from test_samples_seed_contract import _wrapped_candidate
from test_sdk_candidate_contracts import _DATA

from screamingface_engine.benchmarks.failures import CandidateExecutionError
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run

_QUORUM_VOTE = (_DATA / "quorum_vote_candidate.url4").read_text(encoding="utf-8").removesuffix("\n")
_QUORUM_JUDGE = (
    (_DATA / "quorum_judge_vote_candidate.url4").read_text(encoding="utf-8").removesuffix("\n")
)
_VOTE_MODELS = {
    "prov/alpha": ("B", "0.001"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("C", "0.001"),
}
_JUDGE_MODELS = {
    "prov/alpha": ("alpha says 12", "0.001"),
    "prov/beta": ("beta says 7", "0.001"),
    "prov/gamma": ("gamma says 12", "0.001"),
    "prov/judge": (json.dumps({"member_1": 1, "member_2": 5}), "0.001"),
}


def _failing(
    models: Mapping[str, tuple[str, str]],
    failing: Collection[str],
    seen: list[dict[str, Any]],
) -> Callable[[httpx.Request], httpx.Response]:
    answer = _gateway(models, "miss", seen.append)

    def handle(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] in failing:
            seen.append(json.loads(request.content))
            return httpx.Response(400, json={"error": {"message": "provider refused"}})
        return answer(request)

    return handle


async def _run(
    candidate: str,
    models: Mapping[str, tuple[str, str]],
    failing: Collection[str],
    seen: list[dict[str, Any]],
) -> dict[str, Any]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_failing(models, failing, seen)),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=next(iter(models)), models=tuple(ModelSpec(id=model) for model in models)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        with request_scope(RequestScope(origin="run")):
            result = await url4_run(_wrapped_candidate(candidate), io=world.node)
    finally:
        await world.aclose()
        await client.aclose()
    record: dict[str, Any] = json.loads(result)
    return record


def _members(record: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    combine = operation(record, "op_synthesis_1")["combine"]
    return [(m["member_id"], m["status"], m["reason"]) for m in combine["members"]]


@pytest.mark.asyncio
async def test_sdk_quorum_vote_answers_when_the_optional_member_fails() -> None:
    record = await _run(_QUORUM_VOTE, _VOTE_MODELS, ["prov/gamma"], [])

    assert record["status"] == "completed"
    assert record["output"] == "B"
    assert _members(record) == [
        ("member_1", "answered", None),
        ("member_2", "answered", None),
        ("member_3", "fail", "missing"),
    ]
    assert operation(record, "op_synthesis_1")["combine"]["dropped"] == 1


@pytest.mark.asyncio
async def test_sdk_quorum_vote_with_every_member_answering_counts_all_three() -> None:
    record = await _run(_QUORUM_VOTE, _VOTE_MODELS, [], [])

    assert record["output"] == "B"
    assert [status for _, status, _ in _members(record)] == ["answered"] * 3


@pytest.mark.asyncio
async def test_sdk_quorum_vote_stops_when_a_required_member_fails() -> None:
    seen: list[dict[str, Any]] = []
    with pytest.raises(CandidateExecutionError, match="400"):
        await _run(_QUORUM_VOTE, _VOTE_MODELS, ["prov/beta"], seen)


@pytest.mark.asyncio
async def test_sdk_quorum_judge_scores_only_the_members_that_answered() -> None:
    seen: list[dict[str, Any]] = []
    record = await _run(_QUORUM_JUDGE, _JUDGE_MODELS, ["prov/gamma"], seen)

    # The judge trusts member_2 (7) over member_1 (12); member_3 failed and has no weight.
    assert record["output"] == "beta says 7"
    assert _members(record)[2] == ("member_3", "fail", "missing")
    judge = next(body for body in seen if body["model"] == "prov/judge")
    assert judge["messages"][0]["content"].startswith("judge-template@1 returns=scores input=panel")
    panel = json.loads(json.loads(judge["messages"][-1]["content"])["panel"])
    assert [row["source_name"] for row in panel] == ["member_1", "member_2"]
    assert "gamma says 12" not in judge["messages"][-1]["content"]
