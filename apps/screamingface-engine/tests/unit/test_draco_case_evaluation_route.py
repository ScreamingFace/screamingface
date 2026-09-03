"""DRACO emits one exact Case Evaluation before benchmark Aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.draco import assets as draco_assets
from screamingface_engine.benchmarks.draco.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    bind_criterion_evaluation,
)
from screamingface_engine.benchmarks.draco.definition import (
    CANONICAL_EXAM,
    CASE_EVALUATION_ROUTE,
    CASES_ROUTE,
    CRITERION_EVALUATION_ROUTE,
    DRACO,
)
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA
from screamingface_engine.benchmarks.draco.runtime import install
from screamingface_engine.benchmarks.draco.verdict import SCHEMA as VERDICT_SCHEMA
from url4 import RelExpr, RelUrl, Text, expr, render, src
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


async def _call(node: Url4Node, path: str, context: object, intent: str) -> object:
    expression = expr(
        src(Text(json.dumps(context)), name="payload", weight=0.0),
        src(
            RelExpr(path=path, context="$payload", intent=Text(intent)),
            name="result",
            weight=0.0,
        ),
        intent=Text("$result"),
    )
    return json.loads((await node.evaluate(render(expression))).text)


def _one_case_assets(root: Path) -> None:
    (root / "criteria").mkdir(parents=True)
    (root / "rubrics").mkdir()
    (root / "cases.json").write_text('[{"id":1,"input":"Question 1"}]', encoding="utf-8")
    (root / "criteria" / "1.json").write_text(
        '[{"id":"c1","requirement":"Be correct","criterion_type":"positive"}]',
        encoding="utf-8",
    )
    (root / "rubrics" / "1.json").write_text(
        '{"sections":[{"id":"accuracy","criteria":[{"id":"c1","weight":1}]}]}',
        encoding="utf-8",
    )


def _canonical_assets(root: Path) -> None:
    _one_case_assets(root)
    cases = [{"id": case_id, "input": f"Question {case_id}"} for case_id in range(1, 101)]
    (root / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    criterion = (root / "criteria" / "1.json").read_text(encoding="utf-8")
    rubric = (root / "rubrics" / "1.json").read_text(encoding="utf-8")
    for case_id in range(2, 101):
        (root / "criteria" / f"{case_id}.json").write_text(criterion, encoding="utf-8")
        (root / "rubrics" / f"{case_id}.json").write_text(rubric, encoding="utf-8")


def test_draco_builds_exact_criterion_and_case_evaluations() -> None:
    url4 = DRACO.resource(1)["url4"]

    assert isinstance(url4, str)
    assert url4.count(CRITERION_EVALUATION_ROUTE) == 1
    assert url4.count(CASE_EVALUATION_ROUTE) == 1


@pytest.mark.asyncio
async def test_runtime_packs_one_criterion_then_one_case_evaluation(tmp_path: Path) -> None:
    _canonical_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, CANONICAL_EXAM)
    case = {
        "schema": CASE_SCHEMA,
        "case_id": 1,
        "status": "completed",
        "input": "Question 1",
        "answer": "Answer 1",
        "output": "Answer 1",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
        "metadata": {},
    }
    check = {
        "schema": CHECK_SCHEMA,
        "case_id": 1,
        "criterion_id": "c1",
        "criterion_type": "positive",
        "requirement": "Be correct",
    }
    verdicts = [
        {
            "schema": VERDICT_SCHEMA,
            "case_id": 1,
            "criterion_id": "c1",
            "sequence": sequence,
            "producer_type": "model",
            "producer_id": "fixture-judge",
            "valid": True,
            "explanation": "The requirement is met.",
            "criterion_status": "MET",
            "raw_output": '{"criterion_status":"MET"}',
        }
        for sequence in range(1, 6)
    ]
    criterion = await _call(
        node,
        CRITERION_EVALUATION_ROUTE,
        {
            "case": json.dumps(case),
            "check": json.dumps(check),
            **{
                f"evidence_{sequence}": json.dumps(verdict)
                for sequence, verdict in enumerate(verdicts, 1)
            },
        },
        "1",
    )

    result = await _call(node, CASE_EVALUATION_ROUTE, [criterion], "1")

    assert result == {
        "schema": CASE_EVALUATION_SCHEMA,
        "case": case,
        "checks": [check],
        "evidence": verdicts,
    }


def test_case_record_requires_explicit_execution_provenance() -> None:
    case = {
        "schema": CASE_SCHEMA,
        "case_id": 1,
        "status": "completed",
        "input": "Question 1",
        "answer": "Answer 1",
        "output": "Answer 1",
        "finish_reason": "stop",
        "refusal": None,
        "metadata": {},
    }
    check = {
        "schema": CHECK_SCHEMA,
        "case_id": 1,
        "criterion_id": "c1",
        "criterion_type": "positive",
        "requirement": "Be correct",
    }
    evidence = {
        "schema": VERDICT_SCHEMA,
        "case_id": 1,
        "criterion_id": "c1",
        "sequence": 1,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": True,
        "explanation": "The requirement is met.",
        "criterion_status": "MET",
        "raw_output": '{"criterion_status":"MET"}',
    }

    with pytest.raises(ValueError, match="invalid Case record"):
        bind_criterion_evaluation(1, case, check, [evidence])


# WHY these two tests were REWRITTEN (OME-999, owner-approved): install used to validate
# assets ATOMICALLY, refusing to register routes over a broken asset set. That eager read
# meant a Runner world — which installs EVERY registered board — required DRACO's assets to
# run any other board. Install is now lazy (the shared contract HealthBench's install
# documents); the protection moves to resolution: a DRACO run's first touch is its cases
# route, so a broken asset still fails before any model spend, with the same named error —
# on EVERY resolution, since failures are never memoized.


async def _fetch_cases(node: Url4Node) -> str:
    expression = expr(
        src(RelUrl(CASES_ROUTE), name="result", weight=0.0),
        intent=Text("$result"),
    )
    return (await node.evaluate(render(expression))).text


@pytest.mark.asyncio
async def test_missing_assets_fail_every_cases_resolution_by_name(tmp_path: Path) -> None:
    node = Url4Node("test")
    install(node, tmp_path, CANONICAL_EXAM)

    for _attempt in range(2):  # never memoized: the second resolution fails identically
        with pytest.raises(ResolutionError, match="could not read DRACO cases"):
            await _fetch_cases(node)


@pytest.mark.asyncio
async def test_a_truncated_case_set_fails_resolution_with_the_expected_count(
    tmp_path: Path,
) -> None:
    _one_case_assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path, CANONICAL_EXAM)

    with pytest.raises(ResolutionError, match="expected 100 DRACO cases"):
        await _fetch_cases(node)


def test_asset_validation_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    _one_case_assets(tmp_path)
    cases = [{"id": 1, "input": "Question"}, {"id": 1, "input": "Duplicate"}]

    with pytest.raises(ValueError, match="repeats case_id 1"):
        draco_assets.validate_protocol_assets(tmp_path, cases)


def test_asset_validation_rejects_empty_case_input(tmp_path: Path) -> None:
    _one_case_assets(tmp_path)

    with pytest.raises(ValueError, match="non-empty input"):
        draco_assets.validate_protocol_assets(tmp_path, [{"id": 1, "input": ""}])


def test_asset_validation_rejects_an_empty_canonical_rubric(tmp_path: Path) -> None:
    _one_case_assets(tmp_path)
    (tmp_path / "criteria" / "1.json").write_text("[]", encoding="utf-8")
    (tmp_path / "rubrics" / "1.json").write_text('{"sections":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="no DRACO rubric criteria"):
        draco_assets.validate_protocol_assets(
            tmp_path,
            [{"id": 1, "input": "Question"}],
        )
