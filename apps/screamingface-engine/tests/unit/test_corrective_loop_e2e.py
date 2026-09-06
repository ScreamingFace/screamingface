"""End-to-end: a CLIENT-compiled corrective loop executes on this engine.

FEATURE: benchmark-independent corrective loop (OME-796) — both halves meeting.
STORY: as the transport contract, the url4 under tests/unit/data/ was rendered
by `screamingface`'s compiler (sf.CorrectiveLoop / sf.SelfCorrective against
IFEval's advertised check surface) and must run VERBATIM on a world holding the
canonical IFEval benchmark plus the generic corrective runtime — byte-identical
goldens are our side of the contract, and this file re-bakes when either side's
protocol changes.

The scenarios pin the LANL cost story with real request counts:
- a round-1 pass costs exactly N member calls (no judge, no retries);
- a no-pass round buys ONE judge coaching call plus one retry round;
- the passing draft is submitted word-for-word and scores 1.0 canonically.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.ensemble import install_corrective_runtime
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world_config import ModelSpec

pytestmark = pytest.mark.asyncio

_DATA = Path(__file__).parent / "data"
_CASE_PROMPT = "Describe tea without commas."
# Graded against the two-constraint spec below (no_comma + english_lowercase):
_FAIL_ANSWER = "Tea, is nice."  # comma + capital -> satisfaction 0.0
_HALF_ANSWER = "Tea is warm and calming"  # capital -> satisfaction 0.5
_PASS_ANSWER = "tea is warm and calming"  # passes both


def _assets(root: Path) -> None:
    (root / "instructions").mkdir(parents=True)
    (root / "cases.json").write_text(
        json.dumps([{"id": 1, "input": _CASE_PROMPT}]), encoding="utf-8"
    )
    (root / "instructions" / "1.json").write_text(
        json.dumps(
            {
                "key": 1,
                "prompt": _CASE_PROMPT,
                "instruction_id_list": [
                    "punctuation:no_comma",
                    "change_case:english_lowercase",
                ],
                "kwargs": [{}, {}],
            }
        ),
        encoding="utf-8",
    )


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _respond(
    calls: list[tuple[str, str]],
    *,
    member_a_first_round_passes: bool,
    member_b_first_round_passes: bool,
    member_b_refuses: bool,
    member_b_retry_passes: bool,
):
    """Deterministic panel: member-a never passes; member-b improves on coaching."""

    def _member_b(content: str) -> str:
        # member-b: coached (or configured-lucky) drafts pass; first drafts vary.
        if "telling yourself" in content:
            return "Use lowercase and drop the comma."
        coached = "Judge feedback:" in content or "Feedback:" in content
        return (
            _PASS_ANSWER
            if member_b_first_round_passes or coached and member_b_retry_passes
            else _HALF_ANSWER
        )

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        content = " ".join(str(message["content"]) for message in body["messages"])
        calls.append((model, content))
        if model == "prov/member-b" and member_b_refuses:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": None, "refusal": _PASS_ANSWER},
                            "finish_reason": "content_filter",
                        }
                    ]
                },
            )
        replies = {
            "prov/judge": "Remove the comma and write everything in lowercase.",
            "prov/member-a": _PASS_ANSWER if member_a_first_round_passes else _FAIL_ANSWER,
        }
        return _chat(replies.get(model) or _member_b(content))

    return respond


async def _run(
    tmp_path: Path,
    candidate_file: str,
    *,
    member_a_first_round_passes: bool = False,
    member_b_first_round_passes: bool,
    member_b_refuses: bool = False,
    member_b_retry_passes: bool = True,
) -> tuple[dict[str, object], list[tuple[str, str]]]:
    _assets(tmp_path / "ifeval")
    calls: list[tuple[str, str]] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            _respond(
                calls,
                member_a_first_round_passes=member_a_first_round_passes,
                member_b_first_round_passes=member_b_first_round_passes,
                member_b_refuses=member_b_refuses,
                member_b_retry_passes=member_b_retry_passes,
            )
        ),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="prov/member-a",
            models=(
                ModelSpec(id="prov/member-a"),
                ModelSpec(id="prov/member-b"),
                ModelSpec(id="prov/judge"),
            ),
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_corrective_runtime(world.node)
        BenchmarkRegistry((IFEVAL,)).install(world.node, assets_root=tmp_path)
        # rstrip: the repo's end-of-file hook appends a newline the rendered
        # expression never carries.
        candidate_url4 = (_DATA / candidate_file).read_text(encoding="utf-8").rstrip("\n")
        protocol = IFEVAL.resource(1)["url4"]
        assert isinstance(protocol, str)
        result = await world.node.evaluate(link_candidate(candidate_url4, protocol))
    finally:
        await world.aclose()
        await client.aclose()
    payload = json.loads(result.text)
    assert isinstance(payload, dict)
    return payload, calls


def _first_case(result: dict[str, object]) -> dict[str, object]:
    cases = result["cases"]
    assert isinstance(cases, list)
    case = cases[0]
    assert isinstance(case, dict)
    return case


async def test_a_round_one_pass_costs_exactly_the_member_calls(tmp_path: Path) -> None:
    # INVARIANT (the paper's cost story): a lone round-1 passer buys ZERO judge
    # calls and ZERO retries — 2 member calls, free checks, done.
    result, calls = await _run(
        tmp_path,
        "corrective_loop_candidate.url4",
        member_b_first_round_passes=True,
    )
    assert result["score"] == 1.0
    case = _first_case(result)
    assert case["status"] == "scored"
    # INVARIANT: the selected answer is a member answer VERBATIM.
    assert case["output"] == _PASS_ANSWER
    assert case["stop_reason"] == "passed"
    assert case["rounds_executed"] == 1
    assert [model for model, _ in calls] == ["prov/member-a", "prov/member-b"]


async def test_a_selected_provider_refusal_is_graded_and_published_verbatim(
    tmp_path: Path,
) -> None:
    result, calls = await _run(
        tmp_path,
        "corrective_loop_candidate.url4",
        member_b_first_round_passes=False,
        member_b_refuses=True,
    )
    assert result["score"] == 1.0
    case = _first_case(result)
    # INVARIANT (OME-1037): a graded refusal publishes as an ordinary scored Case.
    assert case["status"] == "scored"
    assert case["output"] is None
    assert case["refusal"] == _PASS_ANSWER
    assert case["finish_reason"] == "content_filter"
    assert case["stop_reason"] == "passed"
    assert case["rounds_executed"] == 1
    grade = case["grade"]
    assert isinstance(grade, dict)
    assert grade["score"] == 1.0
    assert case["failures"] == []
    assert [model for model, _ in calls] == ["prov/member-a", "prov/member-b"]


async def test_a_provider_refusal_does_not_abort_a_passing_sibling(
    tmp_path: Path,
) -> None:
    result, calls = await _run(
        tmp_path,
        "corrective_loop_candidate.url4",
        member_a_first_round_passes=True,
        member_b_first_round_passes=False,
        member_b_refuses=True,
    )
    assert result["score"] == 1.0
    case = _first_case(result)
    assert case["status"] == "scored"
    assert case["output"] == _PASS_ANSWER
    assert case["refusal"] is None
    assert case["stop_reason"] == "passed"
    assert case["rounds_executed"] == 1
    assert case["failures"] == []
    # Both texts pass the benchmark checker, so the generic tie-break path runs;
    # the refusal remains a normal checked member rather than aborting the panel.
    assert [model for model, _ in calls] == ["prov/member-a", "prov/member-b", "prov/judge"]


async def test_a_no_pass_round_buys_one_coaching_call_and_a_retry(tmp_path: Path) -> None:
    result, calls = await _run(
        tmp_path,
        "corrective_loop_candidate.url4",
        member_b_first_round_passes=False,
    )
    assert result["score"] == 1.0
    assert _first_case(result)["output"] == _PASS_ANSWER
    assert _first_case(result)["stop_reason"] == "passed"
    assert _first_case(result)["rounds_executed"] == 2
    models = [model for model, _ in calls]
    # Round 1 (a+b, no passer) -> judge coaching -> round 2 (a+b, b passes).
    assert sorted(models[:2]) == ["prov/member-a", "prov/member-b"]
    assert models[2] == "prov/judge"
    assert sorted(models[3:]) == ["prov/member-a", "prov/member-b"]
    # The coached retry threads the judge's words and the member's own draft.
    retry_prompts = [content for model, content in calls[3:]]
    assert all("Judge feedback:" in content for content in retry_prompts)
    member_b_retry = next(content for model, content in calls[3:] if model == "prov/member-b")
    assert _HALF_ANSWER in member_b_retry  # its OWN previous answer, not a's


async def test_self_corrective_coaches_itself_between_rounds(tmp_path: Path) -> None:
    result, calls = await _run(
        tmp_path,
        "self_corrective_candidate.url4",
        member_b_first_round_passes=False,
    )
    assert result["score"] == 1.0
    assert _first_case(result)["output"] == _PASS_ANSWER
    models = [model for model, _ in calls]
    # Draft (fail) -> self-authored coaching -> coached retry (pass).
    assert models == ["prov/member-b", "prov/member-b", "prov/member-b"]
    assert "telling yourself" in calls[1][1]
    assert "Feedback:" in calls[2][1]


async def test_a_never_passing_loop_reports_its_round_limit(tmp_path: Path) -> None:
    result, _calls = await _run(
        tmp_path,
        "corrective_loop_candidate.url4",
        member_b_first_round_passes=False,
        member_b_retry_passes=False,
    )

    case = _first_case(result)
    assert case["stop_reason"] == "max_rounds"
    assert case["rounds_executed"] == 2
