"""Complete DRACO Case evidence survives the public Candidate-result seam.

FEATURE: OME-319 — a completed Evaluation remains auditable after its live stream ends.
STORY: as a researcher, I can read exactly what was asked, what the Candidate answered, what the
Judge returned, and why that reply produced its normalized criterion status.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from benchmark_support import install_benchmarks

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco import runtime as draco_runtime
from screamingface_engine.benchmarks.draco.definition import CANONICAL_EXAM, DRACO, JUDGE_MODEL
from screamingface_engine.grading_accounting import capture_grading_requests
from screamingface_engine.operation_calls import (
    capture_operation_calls,
    capture_request_accounting,
)
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world_config import ModelSpec
from url4 import Node, RelExpr, build, expr, render, src, text
from url4.peer.server import Request

_QUESTION = "What is two plus two?"
_ANSWER = "Four."
_EXPLANATION = "The response states that two plus two is four."
_RAW_JUDGE_REPLY = json.dumps(
    {"explanation": _EXPLANATION, "criterion_status": "MET"},
    indent=2,
)


def _assets(root: Path) -> None:
    (root / "criteria").mkdir(parents=True)
    (root / "rubrics").mkdir()
    cases = [
        {
            "id": case_id,
            "input": _QUESTION if case_id == 1 else f"Question {case_id}",
            "domain": "Arithmetic",
        }
        for case_id in range(1, 101)
    ]
    (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    criteria = [
        {
            "id": "answer-is-four",
            "requirement": "States that two plus two equals four.",
            "criterion_type": "positive",
        }
    ]
    rubric = {
        "sections": [
            {
                "id": "correctness",
                "criteria": [{"id": "answer-is-four", "weight": 3}],
            }
        ]
    }
    for case_id in range(1, 101):
        (root / "criteria" / f"{case_id}.json").write_text(json.dumps(criteria), encoding="utf-8")
        (root / "rubrics" / f"{case_id}.json").write_text(json.dumps(rubric), encoding="utf-8")


def _link(candidate: Node, benchmark: Node) -> str:
    return render(
        expr(
            src(text(render(candidate)), name="candidate", weight=0.0),
            benchmark,
            intent=text(""),
        )
    )


def test_task_rows_render_each_criterion_prompt_once_across_judge_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "draco"
    _assets(root)
    render_context = Mock(wraps=draco_runtime.judge_context)
    render_intent = Mock(wraps=draco_runtime.judge_intent)
    monkeypatch.setattr(draco_runtime, "judge_context", render_context)
    monkeypatch.setattr(draco_runtime, "judge_intent", render_intent)
    handler = draco_runtime._task_rows(root, CANONICAL_EXAM)

    with capture_grading_requests():
        rows = json.loads(
            handler(
                Request(
                    path=CANONICAL_EXAM.routes.tasks,
                    context=encode_candidate_invocation(_ANSWER, "stop", None),
                    intent="1",
                    params={},
                )
            )
        )

    assert len(rows) == 1
    assert render_context.call_count == 1
    assert render_intent.call_count == 1


@pytest.mark.asyncio
async def test_canonical_draco_retains_complete_case_evidence(tmp_path: Path) -> None:
    _assets(tmp_path / "draco")

    def respond(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        content = _ANSWER if model == "openrouter/anthropic/claude-opus-4.8" else _RAW_JUDGE_REPLY
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    candidate = RelExpr(
        path="/openrouter/anthropic/claude-opus-4.8",
        context="$input",
        intent=text("Answer exactly."),
    )
    benchmark = DRACO.resource(1)["url4"]
    assert isinstance(benchmark, str)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url="http://aigateway.test",
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                default_model="openrouter/anthropic/claude-opus-4.8",
                models=(
                    ModelSpec(id="openrouter/anthropic/claude-opus-4.8"),
                    ModelSpec(id=JUDGE_MODEL),
                ),
            ),
            client=client,
        )
        install_benchmarks(world.node, tmp_path, benchmarks=(DRACO,))
        try:
            with capture_operation_calls() as operation_calls:
                with capture_request_accounting():
                    with capture_grading_requests():
                        result = await world.node.evaluate(_link(candidate, build(benchmark)))
        finally:
            await world.aclose()

    decoded = json.loads(result.text)
    assert len(operation_calls) == 5
    assert decoded["cases"] == [
        {
            "status": "scored",
            "case_id": 1,
            "input": _QUESTION,
            "output": _ANSWER,
            "finish_reason": "stop",
            "refusal": None,
            "stop_reason": None,
            "rounds_executed": None,
            "grade": {
                "method": "rubric",
                "score": 1.0,
                "metrics": {
                    "normalized_score_sd": 0.0,
                    "pass_rate": 1.0,
                    "pass_rate_sd": 0.0,
                    # This rubric has no Factual Accuracy axis, so accuracy is unknown rather
                    # than zero — a scored-1.0 Case must not report "0% factually accurate".
                    "accuracy": None,
                    "accuracy_pass_rate": None,
                    "axis_scores": {"correctness": 1.0},
                    "axis_pass_rates": {"correctness": 1.0},
                    "coverage": 1.0,
                    "coverage_sd": 0.0,
                    "n_runs": 5,
                    "verdicts_expected": 5,
                    "verdicts_accepted": 5,
                    "verdicts_rejected": 0,
                    "verdicts_invalid": 0,
                    "verdicts_missing": 0,
                },
                "checks": [
                    {
                        "type": "criterion",
                        "id": "answer-is-four",
                        "label": "States that two plus two equals four.",
                        "evidence": [
                            {
                                "sequence": sequence,
                                "producer": {"type": "model", "id": JUDGE_MODEL},
                                "valid": True,
                                "outcome": "MET",
                                "explanation": _EXPLANATION,
                                "raw_output": _RAW_JUDGE_REPLY,
                                "accounting": {
                                    "provider": "openrouter",
                                    "request_model": JUDGE_MODEL,
                                    "response_model": None,
                                    "usage": {
                                        "input_tokens": 1,
                                        "output_tokens": 1,
                                        "cache_read_tokens": None,
                                        "cache_creation_tokens": None,
                                        "reasoning_tokens": None,
                                        "cost_usd": None,
                                    },
                                    "provider_latency_ms": None,
                                    "cache": {
                                        "hits": 0,
                                        "misses": 0,
                                        "bypasses": 0,
                                        "unknown": 1,
                                    },
                                },
                                "metadata": {},
                            }
                            for sequence in range(1, 6)
                        ],
                        "metadata": {
                            "criterion_type": "positive",
                            "weight": 3,
                            "axis": "correctness",
                        },
                        # OME-848: the 5 passes fold to their majority verdict.
                        "outcome": "MET",
                    }
                ],
            },
            "failures": [],
            "metadata": {"domain": "Arithmetic"},
        }
    ]
