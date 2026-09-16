"""The imported `inspect-mmlu` proof board — the MCQ declaration shape (OME-1115).

INVARIANT the suite defends: an MCQ board bakes their SINGLE_ANSWER prompt as data,
grades through their real `choice()` scorer via the shim's choices replay, and is
REFUSED a check surface — pass/fail feedback over a handful of options is an
elimination attack (OME-796), so the client preflight's refusal of a loop recipe is
correct behavior this board must preserve. Together with gsm8k this covers both
declaration shapes the importer (OME-1116) can produce.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.case_execution import case_execution_payload  # noqa: E402
from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine_inspect.boards import (
    board_registrations,  # noqa: E402
    imported_board,  # noqa: E402
)
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine_inspect.prepare import SNAPSHOTS, emit_snapshot  # noqa: E402

GSM8K_BOARD = imported_board("gsm8k")
MMLU_BOARD = imported_board("mmlu")
from url4 import RelExpr, Text, expr, render, src, text  # noqa: E402
from url4.peer.server import Url4Node  # noqa: E402

_ROWS: list[dict[str, Any]] = [
    {
        "question": "Pick B.",
        "choices": ["no", "yes", "never", "maybe"],
        "answer": 1,
        "subject": "s",
    },
    {
        "question": "Pick A.",
        "choices": ["yes", "no", "never", "maybe"],
        "answer": 0,
        "subject": "s",
    },
    {
        "question": "Pick D.",
        "choices": ["no", "never", "maybe", "yes"],
        "answer": 3,
        "subject": "s",
    },
]


# ── plugin registration (both proof boards, catalogue order) ─────────────────


def test_board_registrations_contribute_both_proof_boards() -> None:
    ids = [registration.benchmark.id for registration in board_registrations()]
    assert ids == ["inspect-gsm8k", "inspect-mmlu"]


def test_revisions_are_sixteen_hex_and_distinct() -> None:
    revisions = {GSM8K_BOARD.benchmark.revision, MMLU_BOARD.benchmark.revision}
    assert len(revisions) == 2
    for revision in revisions:
        assert len(revision) == 16
        int(revision, 16)


# ── definition ───────────────────────────────────────────────────────────────


def test_board_identity_and_mcq_declaration() -> None:
    board = MMLU_BOARD.benchmark
    assert board.id == "inspect-mmlu"
    assert board.declaration.as_block() == {
        "failure_policy": "coverage_declare",
        "interaction": "single_shot",
    }
    assert board.case_count == 14042


def test_mcq_board_is_refused_a_check_surface() -> None:
    """OME-796: no check surface on MCQ — its absence IS the declared contract."""

    assert MMLU_BOARD.benchmark.check_surface is None
    assert "check_surface" not in MMLU_BOARD.benchmark.catalog_entry()


# ── runtime + spine aggregate through their real choice() scorer ─────────────


def _bake(root: Path) -> tuple[Path, dict[int, str]]:
    """Bake the snapshot; return the root and each case's correct letter."""

    out = root / MMLU_BOARD.benchmark.id
    emit_snapshot(SNAPSHOTS["mmlu"], _ROWS, out)
    cases = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    letters = {
        case["id"]: json.loads(
            (out / "targets" / f"{case['id']}.json").read_text(encoding="utf-8")
        )["target"]
        for case in cases
    }
    return root, letters


def _node(root: Path) -> Url4Node:
    node = Url4Node("test")
    MMLU_BOARD.benchmark.install(node, root)
    return node


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


@pytest.mark.asyncio
async def test_aggregate_grades_letters_through_their_choice_scorer(
    tmp_path: Path,
) -> None:
    root, letters = _bake(tmp_path)
    node = _node(root)
    right: str = letters[1]
    wrong: str = next(letter for letter in "ABCD" if letter != letters[2])
    rows = json.dumps([_row(1, f"ANSWER: {right}"), _row(2, f"ANSWER: {wrong}")])
    result = json.loads(await _call(node, MMLU_BOARD.aggregate_route, rows, "aggregate:2"))
    assert result["benchmark_id"] == "inspect-mmlu"
    assert result["score"] == 0.5
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0]


@pytest.mark.asyncio
async def test_an_unparseable_reply_scores_zero_not_a_failure(tmp_path: Path) -> None:
    """Their choice() verdict for a letterless reply is INCORRECT — a grade, not an outage."""

    root, _letters = _bake(tmp_path)
    node = _node(root)
    rows = json.dumps([_row(1, "I refuse to pick a letter.")])
    result = json.loads(await _call(node, MMLU_BOARD.aggregate_route, rows, "aggregate:1"))
    case = result["cases"][0]
    assert case["grade"]["score"] == 0.0
    assert not case.get("failures")
