"""Both HealthBench benchmarks share one answer key without sharing an identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_execution import install_case_execution
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.healthbench.definition import (
    HEALTHBENCH_PROFESSIONAL,
    PROFESSIONAL_VARIANT,
    WORST30_VARIANT,
)
from screamingface_engine.benchmarks.healthbench.pins import JUDGE_MODEL
from screamingface_engine.benchmarks.healthbench.prepare import envelope
from screamingface_engine.benchmarks.healthbench.runtime import install
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS
from url4 import Text, expr, render, src
from url4.peer.server import Request, Url4Node

_MESSAGES = [{"role": "user", "content": "STOP-DAPt trial"}]
_ANSWER = "STOPDAPT-2 studied 1-month DAPT after PCI; which variant do you mean?"


def _write_full_assets(root: Path, points: tuple[int, ...] = (8,)) -> None:
    """The whole baked answer key — all 525 Cases, the superset both benchmarks select from.

    ``points`` is the rubric every Case carries. A positive item is a win a good answer
    earns; a negative one is a penalty. INVARIANT (prepare.py): at least one item must be
    positive, or the score has no denominator — so driving a Case below zero means a small
    win plus a bigger penalty, e.g. ``(2, -8)``.
    """

    root.mkdir(parents=True, exist_ok=True)
    case_ids = tuple(PROFESSIONAL_VARIANT.case_ids)
    (root / "cases.json").write_text(
        json.dumps([{"id": case_id, "input": envelope(_MESSAGES)} for case_id in case_ids]),
        encoding="utf-8",
    )
    rubric_dir = root / "rubrics"
    rubric_dir.mkdir(exist_ok=True)
    for case_id in case_ids:
        (rubric_dir / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "hf_id": f"hf-{case_id}",
                    "items": [
                        {"rubric_id": index, "criterion": f"criterion {index}", "points": value}
                        for index, value in enumerate(points, start=1)
                    ],
                }
            ),
            encoding="utf-8",
        )


@pytest.mark.asyncio
async def test_both_benchmarks_serve_one_answer_key_from_separate_addresses(tmp_path: Path) -> None:
    """INVARIANT (OME-903): two benchmarks, ONE baked asset root, zero route collisions.

    The professional benchmark is a second SELECTION over the same `cases.json` — never a
    second bake and never a renumbering. Installing both into one Runner world must
    therefore work, and each benchmark must serve exactly its own case list.
    """

    _write_full_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, WORST30_VARIANT)
    install(node, tmp_path, PROFESSIONAL_VARIANT)

    professional_routes = PROFESSIONAL_VARIANT.routes
    assert professional_routes.cases != WORST30_VARIANT.routes.cases

    worst30_cases = json.loads(
        (await node.evaluate(f"{WORST30_VARIANT.routes.cases}()!'157'")).text
    )
    professional_cases = json.loads(
        (await node.evaluate(f"{professional_routes.cases}()!'525'")).text
    )
    assert [case["id"] for case in worst30_cases] == list(WORST30_CASE_IDS)
    assert [case["id"] for case in professional_cases] == list(range(1, 526))
    # The hard subset is a strict subset of the full benchmark — same ids, same answer key.
    assert set(WORST30_CASE_IDS) <= {case["id"] for case in professional_cases}
    # INVARIANT: the answer key stays private on BOTH benchmarks — a Candidate sees chat
    # envelopes and nothing of the rubric, whichever benchmark it is sitting.
    served = json.dumps(professional_cases)
    assert "rubric" not in served
    assert "criterion" not in served


@pytest.mark.asyncio
async def test_the_official_clip_reaches_the_score_through_the_real_expression(
    tmp_path: Path,
) -> None:
    """The professional benchmark's whole point, end to end: a negative run reports 0.0.

    Unit-testing ``clipped_mean`` proves the arithmetic; only resolving the BUILT
    expression proves the benchmark actually wired that arithmetic into its aggregate route.
    The rubric here is a +2 win and a -8 penalty, both judged MET, so the one graded Case
    scores (2 - 8) / 2 = -3.0 — the challenge metric would publish -3.0, the official
    metric publishes 0.0.
    """

    _write_full_assets(tmp_path, points=(2, -8))
    node = Url4Node("test")
    install(node, tmp_path, PROFESSIONAL_VARIANT)
    install_case_execution(node)

    @node.endpoint(CANDIDATE_ROUTE)
    def candidate(request: Request) -> str:
        return encode_candidate_invocation(_ANSWER, "stop", None)

    @node.endpoint(f"/{JUDGE_MODEL}")
    def judge(request: Request) -> str:
        # The judge says the PENALTY criterion was triggered — the worst possible answer.
        return '{"explanation": "invents a dosage", "criteria_met": true}'

    expression = expr(
        src(Text("unused-candidate-recipe"), name="candidate", weight=0.0),
        src(HEALTHBENCH_PROFESSIONAL.protocol(1), name="exam", weight=0.0),
        intent=Text("$exam"),
    )
    result = json.loads((await node.evaluate(render(expression))).text)

    assert result["score"] == 0.0, result["cases"]
    # The Case's own grade keeps the unclamped truth — only the benchmark total is floored.
    assert result["cases"][0]["grade"]["score"] == -3.0
    assert result["benchmark_id"] == "healthbench-professional"
