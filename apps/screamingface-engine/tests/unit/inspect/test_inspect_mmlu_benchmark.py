"""The imported `inspect-mmlu` proof benchmark — the MCQ declaration shape (OME-1115).

INVARIANT the suite defends: an MCQ benchmark prepares their SINGLE_ANSWER prompt as data,
grades through their real `choice()` scorer via the scorer adapter's choices replay, and is
REFUSED a draft-feedback offer — pass/fail feedback over a handful of options is an
elimination attack (OME-796), so the client preflight's refusal of a loop recipe is
correct behavior this benchmark must preserve. Together with gsm8k this covers both
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

from replayed_cases_helpers import prepare_with_stand_in_hub  # noqa: E402

from screamingface_engine.benchmarks.contract import encode_candidate_invocation  # noqa: E402
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload  # noqa: E402
from screamingface_engine_inspect.benchmarks import (
    benchmark_registrations,  # noqa: E402
    imported_benchmark,  # noqa: E402
)
from screamingface_engine_inspect.envelopes import (  # noqa: E402
    CHECK_SCHEMA,
    build_case_grade,
)

GSM8K_BENCHMARK = imported_benchmark("gsm8k")
MMLU_BENCHMARK = imported_benchmark("mmlu")
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


# ── plugin registration (both proof benchmarks, catalogue order) ─────────────────


def test_benchmark_registrations_contribute_both_proof_benchmarks() -> None:
    # AIDEV-NOTE: amended for OME-1116 milestone C — the catalogue now holds more
    # imported benchmarks, so the proof benchmarks are asserted PRESENT and in catalogue
    # order, not the whole list (test_inspect_imported_benchmarks.py owns the full set).
    ids = [registration.benchmark.id for registration in benchmark_registrations()]
    assert ids.index("inspect-gsm8k") < ids.index("inspect-mmlu")


def test_revisions_are_sixteen_hex_and_distinct() -> None:
    revisions = {GSM8K_BENCHMARK.benchmark.revision, MMLU_BENCHMARK.benchmark.revision}
    assert len(revisions) == 2
    for revision in revisions:
        assert len(revision) == 16
        int(revision, 16)


# ── definition ───────────────────────────────────────────────────────────────


def test_benchmark_identity_and_mcq_declaration() -> None:
    benchmark = MMLU_BENCHMARK.benchmark
    assert benchmark.id == "inspect-mmlu"
    assert benchmark.declaration.as_block() == {
        "failure_policy": "coverage_declare",
        "interaction": "single_shot",
        # OME-1257: broad knowledge with headroom, no expert-frontier stakes.
        "difficulty": "medium",
    }
    # OME-1460: inspect's own filter_duplicate_ids drops 105 repeated questions.
    assert benchmark.case_count == 13937


def test_mcq_benchmark_is_refused_a_check_surface() -> None:
    """OME-796: no draft-feedback offer on MCQ — its absence IS the declared contract."""

    assert MMLU_BENCHMARK.benchmark.check_surface is None
    assert "check_surface" not in MMLU_BENCHMARK.benchmark.catalog_entry()


# ── runtime + shared-grading aggregate through their real choice() scorer ─────────────


def _prepare(root: Path) -> tuple[Path, dict[int, str]]:
    """Prepare the prepared cases; return the root and each case's correct letter."""

    out = root / MMLU_BENCHMARK.benchmark.id
    prepare_with_stand_in_hub("mmlu", _ROWS, out)
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
    MMLU_BENCHMARK.benchmark.install(node, root)
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
    return graded_answer_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [build_case_grade(case_id, [record])],
    )


@pytest.mark.asyncio
async def test_aggregate_grades_letters_through_their_choice_scorer(
    tmp_path: Path,
) -> None:
    root, letters = _prepare(tmp_path)
    node = _node(root)
    right: str = letters[1]
    wrong: str = next(letter for letter in "ABCD" if letter != letters[2])
    rows = json.dumps([_row(1, f"ANSWER: {right}"), _row(2, f"ANSWER: {wrong}")])
    result = json.loads(await _call(node, MMLU_BENCHMARK.aggregate_route, rows, "aggregate:2"))
    assert result["benchmark_id"] == "inspect-mmlu"
    assert result["score"] == 0.5
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0]


@pytest.mark.asyncio
async def test_an_unparseable_reply_scores_zero_not_a_failure(tmp_path: Path) -> None:
    """Their choice() verdict for a letterless reply is INCORRECT — a grade, not an outage."""

    root, _letters = _prepare(tmp_path)
    node = _node(root)
    rows = json.dumps([_row(1, "I refuse to pick a letter.")])
    result = json.loads(await _call(node, MMLU_BENCHMARK.aggregate_route, rows, "aggregate:1"))
    case = result["cases"][0]
    assert case["grade"]["score"] == 0.0
    assert not case.get("failures")
