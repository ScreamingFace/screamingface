# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""FrontierScience — the judged proof board (OME-1240 acceptance, board half).

The first LLM-judged import: 160 frontier science problems whose grading is the
eval's OWN judge — olympiad answers against the official grading prompt, research
answers against a per-case rubric — dialed through OUR gateway route. This suite
pins the board's identity (judge in the revision), its declaration (no check
surface until the check-cost knob), and one aggregate where BOTH formats grade
end-to-end through a fake judge endpoint on the node.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.case_execution import case_execution_payload  # noqa: E402
from screamingface_engine.benchmarks.contract import (  # noqa: E402
    encode_candidate_invocation,
)
from screamingface_engine_inspect.boards import BOARDS, imported_board  # noqa: E402
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine_inspect.prepare import SNAPSHOTS  # noqa: E402
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Request, Url4Node  # noqa: E402

BOARD = imported_board("frontierscience")

#: The pinned gateway judge — HealthBench's judge model, dialed as a node route.
_JUDGE_ROUTE = "/openrouter/openai/gpt-5.4"


# ── definition ───────────────────────────────────────────────────────────────


def test_board_identity_and_declaration() -> None:
    board = BOARD.benchmark
    assert board.id == "inspect-frontierscience"
    assert len(board.revision) == 16 and int(board.revision, 16) >= 0
    assert board.case_count == 160
    assert board.declaration.as_block()["difficulty"] == "hard"
    assert board.origin == "inspect_evals"


def test_the_judge_is_declared_and_pinned() -> None:
    """The board dials the SAME judge it declares, and the snapshot bakes the
    metadata its scorer dispatches on."""

    spec = next(spec for spec in BOARDS if spec.key == "frontierscience")
    assert spec.judge == JudgeSpec(
        model="openrouter/openai/gpt-5.4",
        params=(("web_search", "false"), ("max_tokens", "4096")),
    )
    assert spec.scorer_kwargs["model"] == "screamingface/openrouter/openai/gpt-5.4"
    assert SNAPSHOTS["frontierscience"].keep_sample_metadata is True
    assert SNAPSHOTS["frontierscience"].shuffle_seed is not None


def test_no_check_surface_until_the_check_cost_knob() -> None:
    """A judged mid-run check would spend judge tokens while advertising free —
    refused until OME-1116 lands the cost knob."""

    assert BOARD.benchmark.check_surface is None


# ── aggregate: both judge formats grade through the node route ───────────────


class _FormatAwareJudge:
    """A fake gateway judge: olympiad prompts get a GRADE, research prompts a VERDICT."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def __call__(self, request: Request) -> str:
        self.requests.append(request)
        prompt = json.loads(str(request.context))["messages"][-1]["content"]
        if "VERDICT" in prompt:
            # The research template asks for VERDICT: <points> (max 10 → 7.5 ⇒ 0.75).
            return "Partial rubric coverage.\n\nVERDICT: 7.5"
        return "Matches the reference answer.\n\nGRADE: C"


def _bake_by_hand(root: Path) -> None:
    board_root = root / BOARD.benchmark.id
    (board_root / "targets").mkdir(parents=True)
    (board_root / "cases.json").write_text(
        json.dumps(
            [
                {"id": 1, "input": "Compute the muon lifetime."},
                {"id": 2, "input": "Design an assay for protein X."},
            ]
        ),
        encoding="utf-8",
    )
    (board_root / "targets" / "1.json").write_text(
        json.dumps({"target": "2.2 microseconds", "metadata": {"format": "olympic"}}),
        encoding="utf-8",
    )
    (board_root / "targets" / "2.json").write_text(
        json.dumps(
            {
                "target": "Rubric: +5 names a ligand; +5 controls.",
                "metadata": {"format": "research"},
            }
        ),
        encoding="utf-8",
    )


def _row(case_id: int, answer: str) -> dict[str, object]:
    record = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": answer,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
    }
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [bind_case_evaluation(case_id, [record])],
    )


async def _call(node: Url4Node, route: str, payload: str, intent: str) -> str:
    result = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=route, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


@pytest.mark.asyncio
async def test_both_judge_formats_grade_through_the_gateway_route(tmp_path: Path) -> None:
    """One olympiad Case (GRADE: C → 1.0) and one research Case (VERDICT: 7.5 →
    0.75) — the scorer dispatches each on its baked metadata, and every judge
    call exits through the declared node route with the pinned params."""

    judge = _FormatAwareJudge()
    node = Url4Node("test")
    node.endpoint(_JUDGE_ROUTE)(judge)
    _bake_by_hand(tmp_path)
    BOARD.benchmark.install(node, tmp_path)

    rows = json.dumps([_row(1, "2.2 microseconds"), _row(2, "Use ligand L, with controls.")])
    result = json.loads(await _call(node, BOARD.aggregate_route, rows, "aggregate:2"))

    grades = [case["grade"]["score"] for case in result["cases"]]
    assert grades == [1.0, 0.75]
    assert result["score"] == round((1.0 + 0.75) / 2, 4)
    # Two judge calls, both through the declared route, both with pinned params.
    assert len(judge.requests) == 2
    assert all(req.params.get("web_search") == "false" for req in judge.requests)
    assert all(req.params.get("max_tokens") == "4096" for req in judge.requests)
    # The judge's words survive per Case (audit trail).
    rendered = json.dumps(result["cases"][0]["grade"]["checks"])
    assert "Matches the reference answer." in rendered
