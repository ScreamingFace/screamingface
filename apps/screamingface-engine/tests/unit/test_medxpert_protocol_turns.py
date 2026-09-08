"""The two-turn MedXpertQA protocol delivers real inputs to BOTH model calls (OME-1126).

FEATURE: MedXpertQA exact-match MCQ benchmark — official two-turn CoT protocol.

STORY: as a researcher, when I evaluate a model I need turn 1 to carry the case's CoT
prompt and turn 2 (the commit) to carry the question, MY model's turn-1 reasoning, and
the trigger — otherwise the letter being graded is not the model's committed answer.

INVARIANT under test: no model call in the resolved protocol ever ships an empty user
prompt. A live run captured the grading-side call with prompt_tokens=32 (system prompt
only) because `$item.cot_prompt` was read inside `preserve_candidate_outcome`'s
protective iterate, where `$item` is the `{candidate_invocation, case_id}` struct; the
commit envelope's `$reasoning` was likewise unbound in its scope. Evidence: OME-1126
issue comment, 2026-09-08.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.contract import CandidateResult
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.medxpert.definition import ASSET_BUNDLE_ID, MEDXPERT
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world_config import ModelSpec
from url4 import RelExpr, text

pytestmark = pytest.mark.asyncio

_MODEL = "openrouter/test/candidate"
_OPTIONS = {letter: f"choice {letter}" for letter in "ABCDEFGHIJ"}
_TRIGGER_MARK = "the answer is"


def _row(index: int) -> dict:
    # WHY distinct question text per row: the commit-pairing assertion must be able to
    # tell WHICH case's reasoning reached WHICH commit envelope.
    return {
        "id": f"Text-{index}",
        "question": (
            f"CASE-{index}-QUESTION which agent is indicated? Answer Choices: "
            + " ".join(f"({letter}) {label}" for letter, label in _OPTIONS.items())
        ),
        "options": _OPTIONS,
        "label": "E",
        "medical_task": "Diagnosis",
        "body_system": "Cardiovascular",
        "question_type": "Reasoning",
    }


def _assets(tmp_path: Path, count: int) -> Path:
    emit([_row(i) for i in range(count)], tmp_path / ASSET_BUNDLE_ID)
    return tmp_path


def _message_text(body: dict) -> str:
    return "\n".join(str(message.get("content") or "") for message in body.get("messages", []))


async def _run(tmp_path: Path, case_count: int) -> tuple[CandidateResult, list[dict]]:
    """Resolve the full MedXpertQA protocol against a recording fake gateway."""

    requests: list[dict] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        prompt = _message_text(body)
        if _TRIGGER_MARK in prompt:
            # The commit turn: finish the trigger sentence, letter first.
            content = "(E)"
        else:
            # The reasoning turn: echo which case this essay belongs to.
            case_mark = next(
                (f"REASONING-FOR-CASE-{i}" for i in range(10) if f"CASE-{i}-QUESTION" in prompt),
                "REASONING-WITHOUT-A-CASE",
            )
            content = f"{case_mark} the findings point to option (E)."
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_MODEL, models=(ModelSpec(id=_MODEL),)),
        client=client,
    )
    install_candidate_invocation(world.node)
    BenchmarkRegistry((MEDXPERT,)).install(world.node, assets_root=_assets(tmp_path, case_count))
    candidate_expression = RelExpr(
        path=f"/{_MODEL}", context="$input", intent=text("Answer the question.")
    )
    linked = link_candidate(candidate_expression, MEDXPERT.build(case_count))
    try:
        result = await world.node.evaluate(linked)
    finally:
        await world.aclose()
        await client.aclose()
    return CandidateResult.model_validate(json.loads(result.text)), requests


async def test_no_model_call_ships_an_empty_prompt(tmp_path: Path) -> None:
    """THE OME-1126 LIVE-RUN REGRESSION: a call with only the system prompt is a wasted
    paid call and, on reasoning models, collapses the whole case to UNSCORED."""
    _, requests = await _run(tmp_path, 1)
    assert requests, "the protocol must invoke the model"
    for body in requests:
        user_texts = [
            str(message.get("content") or "")
            for message in body.get("messages", [])
            if message.get("role") == "user"
        ]
        assert user_texts, f"a model call carried no user message: {body.get('messages')}"
        assert all(text.strip() for text in user_texts), (
            f"a model call shipped a blank user prompt: {body.get('messages')}"
        )


async def test_the_commit_turn_carries_question_reasoning_and_trigger(tmp_path: Path) -> None:
    """INVARIANT: turn 2 embeds the model's OWN turn-1 essay — the official protocol.
    Without it the commit degrades to a one-shot letter-last essay, the exact shape the
    first-match commit parser mis-reads (35.5% vs 70.2%, see grading.py)."""
    _, requests = await _run(tmp_path, 1)
    commits = [body for body in requests if _TRIGGER_MARK in _message_text(body)]
    assert len(commits) == 1, "exactly one commit turn per case"
    prompt = _message_text(commits[0])
    assert "CASE-0-QUESTION" in prompt
    assert "REASONING-FOR-CASE-0" in prompt


async def test_each_case_commits_against_its_own_reasoning(tmp_path: Path) -> None:
    result, requests = await _run(tmp_path, 2)
    commits = [body for body in requests if _TRIGGER_MARK in _message_text(body)]
    assert len(commits) == 2
    paired = {
        next(i for i in range(10) if f"CASE-{i}-QUESTION" in _message_text(body)): _message_text(
            body
        )
        for body in commits
    }
    assert "REASONING-FOR-CASE-0" in paired[0]
    assert "REASONING-FOR-CASE-1" in paired[1]
    # WHY score is asserted here too: pairing bugs can leave scoring plausible-looking;
    # with both commits answering (E) against key E the accuracy must be exactly 1.0.
    assert result.score == 1.0


async def test_the_protocol_spends_exactly_two_calls_per_case(tmp_path: Path) -> None:
    """INVARIANT: reason once, commit once. A third call is either a duplicated turn or a
    stray invocation the researcher pays for."""
    _, requests = await _run(tmp_path, 1)
    assert len(requests) == 2, [body.get("model") for body in requests]
