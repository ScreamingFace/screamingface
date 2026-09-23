"""End-to-end: a client-compiled corrective loop runs on DRACO (OME-829).

FEATURE: the corrective loop's benchmark independence, cashed on a rubric
benchmark with a PAID check surface.
STORY: as the transport contract, `tests/unit/data/draco_corrective_loop_candidate.url4`
was rendered by `screamingface`'s compiler against DRACO's advertised check
route — the SAME recipe shape that runs on IFEval, with only the route changed —
and must execute verbatim here, mid-run checks and canonical grading side by
side on one Judge.

The scenarios pin what "works on DRACO" actually means: the check spends a Judge
call per draft, a failing round buys coaching, the winning draft ships verbatim
into the benchmark's own grading, and the rubric never leaks into a retry prompt.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.draco.definition import DRACO, JUDGE_MODEL
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.corrective import install_corrective_runtime

pytestmark = pytest.mark.asyncio

_DATA = Path(__file__).parent / "data"
_QUESTION = "Explain why the sky looks blue."
_REQUIREMENT = "MUST cite Rayleigh scattering"
_WEAK = "The sky is blue because of the ocean."
_STRONG = "Blue light scatters most, by Rayleigh scattering."
_MEMBER_A = "prov/member-a"
_MEMBER_B = "prov/member-b"
_LOOP_JUDGE = "prov/judge"


def _assets(root: Path) -> None:
    draco = root / "draco"
    (draco / "rubrics").mkdir(parents=True)
    (draco / "criteria").mkdir(parents=True)
    cases = [
        {
            "id": case_id,
            "input": _QUESTION if case_id == 1 else f"Question {case_id}",
            "domain": "science",
        }
        for case_id in range(1, 101)
    ]
    (draco / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    rubric = {
        "sections": [
            {
                "id": "Factual Accuracy",
                "criteria": [{"id": "c1", "requirement": _REQUIREMENT, "weight": 1}],
            }
        ]
    }
    criteria = [{"id": "c1", "requirement": _REQUIREMENT, "criterion_type": "positive"}]
    for case_id in range(1, 101):
        (draco / "rubrics" / f"{case_id}.json").write_text(json.dumps(rubric), encoding="utf-8")
        (draco / "criteria" / f"{case_id}.json").write_text(json.dumps(criteria), encoding="utf-8")


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _tavily(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": []})


def _judge_reply(content: str) -> str:
    """One Judge serves BOTH instruments, and both prompts contain the requirement
    text — so "did the ANSWER satisfy it" must key on the answer, never on the
    prompt merely containing the words."""

    met = "MET" if _STRONG in content else "UNMET"
    if "<requirements>" in content:
        # The mid-run check asks about a numbered requirement list.
        return json.dumps([{"id": 1, "status": met}])
    # Canonical grading asks about one criterion and wants a different reply shape.
    return json.dumps({"explanation": "graded", "criterion_status": met})


def _respond(calls: list[tuple[str, str]]):
    """A deterministic panel: member-a never cites, member-b cites once coached."""

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        content = " ".join(str(message["content"]) for message in body["messages"])
        calls.append((model, content))
        if model == JUDGE_MODEL:
            return _chat(_judge_reply(content))
        scripted = {
            _LOOP_JUDGE: "Name the physical scattering mechanism.",
            _MEMBER_A: _WEAK,
        }
        # member-b is the only one that improves when coached.
        coached = "Judge feedback:" in content
        return _chat(scripted.get(model) or (_STRONG if coached else _WEAK))

    return respond


async def _run(tmp_path: Path) -> tuple[dict[str, object], list[tuple[str, str]]]:
    _assets(tmp_path)
    calls: list[tuple[str, str]] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_respond(calls)), base_url="http://aigateway.test"
    )
    # DRACO is retrieval-aware: its Candidate Invocation declares web_search, so the
    # world needs a retrieval route even when no member actually searches.
    tavily = httpx.AsyncClient(
        transport=httpx.MockTransport(_tavily), base_url="https://api.tavily.com"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=_MEMBER_A,
            models=(
                ModelSpec(id=_MEMBER_A),
                ModelSpec(id=_MEMBER_B),
                ModelSpec(id=_LOOP_JUDGE),
                ModelSpec(id=JUDGE_MODEL),
            ),
        ),
        client=client,
        tavily_api_key="tvly-test",
        tavily_client=tavily,
    )
    try:
        install_candidate_invocation(world.node)
        install_corrective_runtime(world.node)
        BenchmarkRegistry((DRACO,)).install(world.node, assets_root=tmp_path)
        candidate = (
            (_DATA / "draco_corrective_loop_candidate.url4")
            .read_text(encoding="utf-8")
            .rstrip("\n")
        )
        protocol = DRACO.resource(1)["url4"]
        assert isinstance(protocol, str)
        result = await world.node.evaluate(link_candidate(candidate, protocol))
    finally:
        await world.aclose()
        await client.aclose()
        await tavily.aclose()
    payload = json.loads(result.text)
    assert isinstance(payload, dict)
    return payload, calls


def _first_case(result: dict[str, object]) -> dict[str, object]:
    cases = result["cases"]
    assert isinstance(cases, list)
    case = cases[0]
    assert isinstance(case, dict)
    return case


async def test_the_loop_corrects_a_weak_draft_and_draco_grades_the_winner(
    tmp_path: Path,
) -> None:
    result, calls = await _run(tmp_path)

    # The loop submitted the coached draft VERBATIM, and DRACO's own grading scored it.
    case = _first_case(result)
    assert case["output"] == _STRONG
    assert result["score"] == 1.0
    assert case["status"] == "scored"

    models = [model for model, _ in calls]
    # Round 1: both members draft, both drafts are checked (PAID), nobody passes.
    assert models[:2] == [_MEMBER_A, _MEMBER_B]
    assert models.count(JUDGE_MODEL) >= 3  # 2 round-1 checks + 2 round-2 checks + grading
    # A no-pass round bought exactly one coaching call from the loop's own judge.
    assert models.count(_LOOP_JUDGE) == 1


async def test_every_mid_run_check_is_a_paid_judge_call(tmp_path: Path) -> None:
    # WHY this test exists: on IFEval the check is free arithmetic, so nothing in
    # the loop's shape reveals cost. On DRACO each check is a real model request —
    # this counts them, which is what the SDK's paid-spend warning promises.
    _, calls = await _run(tmp_path)
    checks = [
        content for model, content in calls if model == JUDGE_MODEL and "<requirements>" in content
    ]
    # 2 members x 2 rounds — the loop ran to its budget because round 1 had no passer.
    assert len(checks) == 4
    for prompt in checks:
        assert _QUESTION in prompt
        assert _REQUIREMENT in prompt


async def test_the_rubric_never_reaches_a_member_retry_prompt(tmp_path: Path) -> None:
    # INVARIANT (sealed envelope): the rubric is the answer key. Feedback flows
    # check -> loop judge -> member prompts, so this walks that whole path and
    # asserts the requirement text never crosses it.
    _, calls = await _run(tmp_path)
    downstream = [
        content for model, content in calls if model in {_MEMBER_A, _MEMBER_B, _LOOP_JUDGE}
    ]
    assert downstream
    for prompt in downstream:
        assert _REQUIREMENT not in prompt
        assert "Rayleigh scattering" not in prompt or _STRONG in prompt


async def test_the_check_and_the_grader_share_one_judge_model(tmp_path: Path) -> None:
    _, calls = await _run(tmp_path)
    graded = [
        content
        for model, content in calls
        if model == JUDGE_MODEL and "<requirements>" not in content
    ]
    # Canonical grading: five independent Judge passes over the selected criterion.
    assert len(graded) == 5
    assert all(_STRONG in prompt for prompt in graded)
