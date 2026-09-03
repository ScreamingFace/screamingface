"""The draco-3pass board: same benchmark, three judge passes, its own identity.

The draco-cache-seed archive covers grading rounds 1-3 only, so this board runs exactly
those three passes — re-running the archived candidates is served fully from the shared
response cache. The canonical five-pass board stays untouched and keeps its frozen
revision.

INVARIANT: the two boards differ in exactly one place — judge passes. The dataset,
criteria, Judge, prompts, and retrieval policy are shared and cannot drift; a different
revision is a different benchmark, so three-pass scores are never compared against
five-pass ones (OME-775).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from benchmark_support import install_benchmarks

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco import aggregate as agg
from screamingface_engine.benchmarks.draco.case_evaluation import (
    bind_case_evaluation,
    bind_criterion_evaluation,
)
from screamingface_engine.benchmarks.draco.definition import (
    CANONICAL_EXAM,
    DRACO,
    DRACO_3PASS,
    JUDGE_MODEL,
    THREE_PASS_EXAM,
)
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from url4 import render
from url4.peer.server import Url4Node

# INVARIANT: the canonical board's address may not move by accident. Every route it
# serves carries this hash and the scoreboard seeds it; a refactor that reshuffles the
# revision math must land on the SAME value (healthbench-worst30 precedent).
# OME-993 moved it DELIBERATELY (from 66a463248586b277): the judge now pins
# reasoning_effort=low (max_tokens stays the paper's 4096), and judge params are hashed
# into the board identity — a different exam is a different revision.
#  Scoreboard seeds, cache seeds, and goldens re-record against this value.
CANONICAL_REVISION = "62718f04ea1a980f"


def _url4(benchmark, limit: int | None = None) -> str:
    return str(benchmark.resource(limit)["url4"])


# --- identity ---------------------------------------------------------------------


def test_the_canonical_revision_is_frozen_against_refactors() -> None:
    assert DRACO.revision == CANONICAL_REVISION
    assert CANONICAL_EXAM.revision == CANONICAL_REVISION


def test_both_draco_boards_are_registered_under_their_own_ids() -> None:
    """INVARIANT: these boards are PUBLIC — dropping one is a leaderboard regression.

    WHY here and not in a shared test (OME-1095): the shared suite iterates the registry, so
    a board deleted from `builtins.py` simply stops being iterated and every cross-benchmark
    test still passes. Membership can only be pinned by a test that names the board, and the
    board's own definition module is where that costs one line per new board instead of an
    edit to every shared test.
    """

    assert BUILTIN_BENCHMARKS.get("draco") is DRACO
    assert BUILTIN_BENCHMARKS.get("draco-3pass") is DRACO_3PASS


def test_both_draco_boards_link_the_perplexity_dataset() -> None:
    # WHY the literal, on both boards: the leaderboard renders this as a clickable target for
    # the public. The shared suite can only check that boards sharing a bundle agree — and
    # both DRACO boards read one constant, so they would agree on a wrong value too.
    assert DRACO.dataset_url == "https://huggingface.co/datasets/perplexity-ai/draco"
    assert DRACO_3PASS.dataset_url == DRACO.dataset_url


def test_the_three_pass_board_has_its_own_identity() -> None:
    assert DRACO_3PASS.id == "draco-3pass"
    assert DRACO_3PASS.title == "DRACO 3-Pass"
    assert DRACO_3PASS.case_count == 100
    assert THREE_PASS_EXAM.judge_passes == 3
    assert DRACO_3PASS.revision != DRACO.revision


def test_the_three_pass_routes_are_revision_pinned_and_separate() -> None:
    assert THREE_PASS_EXAM.revision in _url4(DRACO_3PASS)
    prefix = THREE_PASS_EXAM.routes.prefix
    assert prefix == f"/benchmarks/draco-3pass/{THREE_PASS_EXAM.revision}"
    canonical_routes = {
        CANONICAL_EXAM.routes.cases,
        CANONICAL_EXAM.routes.tasks,
        CANONICAL_EXAM.routes.verdict,
        CANONICAL_EXAM.routes.criterion_evaluation,
        CANONICAL_EXAM.routes.case_evaluation,
        CANONICAL_EXAM.routes.aggregate,
        CANONICAL_EXAM.routes.check_surface,
    }
    three_pass_routes = {
        THREE_PASS_EXAM.routes.cases,
        THREE_PASS_EXAM.routes.tasks,
        THREE_PASS_EXAM.routes.verdict,
        THREE_PASS_EXAM.routes.criterion_evaluation,
        THREE_PASS_EXAM.routes.case_evaluation,
        THREE_PASS_EXAM.routes.aggregate,
        THREE_PASS_EXAM.routes.check_surface,
    }
    assert all(route.startswith(prefix) for route in three_pass_routes)
    assert not (canonical_routes & three_pass_routes)


def test_the_catalogue_serves_both_boards() -> None:
    entry = DRACO_3PASS.catalog_entry()
    assert entry["id"] == "draco-3pass"
    assert entry["case_count"] == 100
    check = entry["check_surface"]
    assert isinstance(check, dict)
    assert check["check_route"].startswith(f"/benchmarks/draco-3pass/{THREE_PASS_EXAM.revision}")


# ── protocol shape ------------------------------------------------------------------


def test_the_three_pass_protocol_renders_exactly_three_verdicts() -> None:
    expression = render(DRACO_3PASS.build(1))

    assert expression.count("/" + JUDGE_MODEL) == 3
    assert expression.count("web_search=false") == 3
    for seed in range(1, 4):
        assert expression.count(f"&seed={seed}") == 1
    assert "&seed=4" not in expression
    for field in ("evidence_1", "evidence_2", "evidence_3"):
        assert expression.count(f"{field}: ") == 1
    assert "evidence_4:" not in expression


def test_the_three_pass_limit_slices_cases_not_judging_strength() -> None:
    full = render(DRACO_3PASS.build(DRACO_3PASS.case_count))
    one_case = render(DRACO_3PASS.build(1))

    # The verdict calls live in the per-criterion iteration TEMPLATE, so their count is
    # the pass count (3), not passes × cases — the case count only slices the selection.
    assert full.count("/" + JUDGE_MODEL) == 3
    assert one_case.count("/" + JUDGE_MODEL) == 3
    assert one_case.count("iteration.slice=0:1") == 1


# ── installation --------------------------------------------------------------------


def _draco_assets(root: Path) -> None:
    assets = root / "draco"
    (assets / "criteria").mkdir(parents=True)
    (assets / "rubrics").mkdir()
    cases = [{"id": case_id, "input": f"Question {case_id}"} for case_id in range(1, 101)]
    (assets / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    criterion = '[{"id":"c1","requirement":"Be correct","criterion_type":"positive"}]'
    rubric = '{"sections":[{"id":"accuracy","criteria":[{"id":"c1","weight":1}]}]}'
    for case_id in range(1, 101):
        (assets / "criteria" / f"{case_id}.json").write_text(criterion, encoding="utf-8")
        (assets / "rubrics" / f"{case_id}.json").write_text(rubric, encoding="utf-8")


def test_both_boards_install_and_validate_on_one_world(tmp_path: Path) -> None:
    _draco_assets(tmp_path)
    node = Url4Node("test")
    install_benchmarks(
        node,
        tmp_path,
        benchmarks=BenchmarkRegistry((DRACO, DRACO_3PASS)),
    )

    registered = set(node.processor_routes())
    for route in (
        CANONICAL_EXAM.routes.tasks,
        CANONICAL_EXAM.routes.verdict,
        CANONICAL_EXAM.routes.criterion_evaluation,
        CANONICAL_EXAM.routes.case_evaluation,
        CANONICAL_EXAM.routes.aggregate,
        CANONICAL_EXAM.routes.check_surface,
        THREE_PASS_EXAM.routes.tasks,
        THREE_PASS_EXAM.routes.verdict,
        THREE_PASS_EXAM.routes.criterion_evaluation,
        THREE_PASS_EXAM.routes.case_evaluation,
        THREE_PASS_EXAM.routes.aggregate,
        THREE_PASS_EXAM.routes.check_surface,
    ):
        assert route in registered
    # The cases routes are DATA routes, not endpoints — same accessor the registry uses.
    data = getattr(node, "_data", {})
    assert CANONICAL_EXAM.routes.cases in data
    assert THREE_PASS_EXAM.routes.cases in data


def test_the_three_pass_install_rejects_evidence_that_is_not_three_wide(
    tmp_path: Path,
) -> None:
    _draco_assets(tmp_path)
    node = Url4Node("test")
    install_benchmarks(
        node,
        tmp_path,
        benchmarks=BenchmarkRegistry((DRACO_3PASS,)),
    )

    # The canonical board's expression (five evidence slots) must not resolve against
    # the three-pass board's criterion-evaluation route: every route is revision-pinned,
    # so the canonical protocol literally addresses a different path.
    assert CANONICAL_EXAM.routes.criterion_evaluation not in node.processor_routes()


# ── aggregation -----------------------------------------------------------------------


_RUBRIC = {
    "sections": [
        {
            "id": "Factual Accuracy",
            "criteria": [
                {"id": "a1", "weight": 2, "requirement": "cites a source"},
                {"id": "a2", "weight": 1, "requirement": "states the date"},
                {"id": "a3", "weight": -3, "requirement": "invents a statistic"},
            ],
        },
        {"id": "Presentation", "criteria": [{"id": "b1", "weight": 1, "requirement": "is terse"}]},
    ]
}


def _selected_cases(*case_ids: int) -> list[dict[str, object]]:
    return [{"id": case_id, "input": f"Question {case_id}"} for case_id in case_ids]


def _verdict(cid: str, status: str, sequence: int = 1) -> dict[str, object]:
    raw = json.dumps({"explanation": "evidence", "criterion_status": status})
    return {
        "schema": "screamingface.criterion-verdict.v1",
        "case_id": 1,
        "criterion_id": cid,
        "sequence": sequence,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": True,
        "explanation": "evidence",
        "criterion_status": status,
        "raw_output": raw,
    }


def _three_pass_row() -> dict[str, object]:
    evidence = {
        cid: [_verdict(cid, status, sequence) for sequence, status in enumerate(statuses, 1)]
        for cid, statuses in {
            "a1": ["MET"] * 3,
            "a2": ["MET"] * 3,
            "a3": ["UNMET"] * 3,
            "b1": ["MET"] * 3,
        }.items()
    }
    case_record = {
        "schema": CASE_SCHEMA,
        "case_id": 1,
        "input": "Question 1",
        "status": "completed",
        "answer": "Answer 1",
        "output": "Answer 1",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
        "metadata": {},
    }
    criteria = []
    for index, criterion_id in enumerate(("a1", "a2", "a3", "b1")):
        criteria.append(
            bind_criterion_evaluation(
                1,
                case_record if index == 0 else None,
                {
                    "schema": CHECK_SCHEMA,
                    "case_id": 1,
                    "criterion_id": criterion_id,
                    "criterion_type": "negative" if criterion_id == "a3" else "positive",
                    "requirement": f"Requirement {criterion_id}",
                },
                evidence[criterion_id],
            )
        )
    return case_execution_payload(
        1,
        encode_candidate_invocation("Answer 1", "stop", None),
        [bind_case_evaluation(1, criteria)],
    )


def test_three_pass_aggregate_carries_the_variant_identity() -> None:
    result = agg.aggregate(
        json.dumps([_three_pass_row()]),
        rubrics={1: _RUBRIC},
        benchmark_id="draco-3pass",
        selected_cases=_selected_cases(1),
        judge_passes=3,
        benchmark_revision=THREE_PASS_EXAM.revision,
    )

    assert result["benchmark_id"] == "draco-3pass"
    assert result["benchmark_revision"] == THREE_PASS_EXAM.revision
    assert result["metrics"]["n_runs"] == 3
    assert result["score"] == 1.0


def _four_pass_row() -> dict[str, object]:
    evidence = {
        "a1": [
            _verdict("a1", "MET", sequence)
            for sequence in (1, 2, 3, 4)  # four passes — the protocol never produces this
        ],
        "a2": [_verdict("a2", "MET", n) for n in (1, 2, 3)],
        "a3": [_verdict("a3", "UNMET", n) for n in (1, 2, 3)],
        "b1": [_verdict("b1", "MET", n) for n in (1, 2, 3)],
    }
    case_record = {
        "schema": CASE_SCHEMA,
        "case_id": 1,
        "input": "Question 1",
        "status": "completed",
        "answer": "Answer 1",
        "output": "Answer 1",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
        "metadata": {},
    }
    criteria = []
    for index, criterion_id in enumerate(("a1", "a2", "a3", "b1")):
        criteria.append(
            bind_criterion_evaluation(
                1,
                case_record if index == 0 else None,
                {
                    "schema": CHECK_SCHEMA,
                    "case_id": 1,
                    "criterion_id": criterion_id,
                    "criterion_type": "negative" if criterion_id == "a3" else "positive",
                    "requirement": f"Requirement {criterion_id}",
                },
                evidence[criterion_id],
            )
        )
    return case_execution_payload(
        1,
        encode_candidate_invocation("Answer 1", "stop", None),
        [bind_case_evaluation(1, criteria)],
    )


def test_a_fourth_pass_aborts_as_protocol_corruption() -> None:
    with pytest.raises(agg.AggregateError, match="more than 3 Judge Evidence"):
        agg.aggregate(
            json.dumps([_four_pass_row()]),
            rubrics={1: _RUBRIC},
            benchmark_id="draco-3pass",
            selected_cases=_selected_cases(1),
            judge_passes=3,
        )


# ── OME-993: judge resilience pins ---------------------------------------------------


def test_the_judge_calls_pin_low_reasoning_a_raised_budget_and_bounded_retry() -> None:
    # INVARIANT: the Judge is a reasoning model — without a reasoning throttle it can
    # burn its whole token budget thinking and return a blank `length` turn (GH #740).
    # The board pins the official low effort (DRACO paper §4.2) over the paper's own
    # max_tokens=4096 (owner decision: reproduce the DRACO parametrization exactly),
    # plus a bounded retry so a transient 429/5xx does not fail the whole Case (url4
    # never retries permanent failures).
    expression = render(DRACO_3PASS.build(1))

    assert expression.count("reasoning_effort=low") == 3
    assert expression.count("max_tokens=4096") == 3
    assert "max_tokens=8192" not in expression
    assert expression.count(";retry=2") == 3
