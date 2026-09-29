"""The IFEval runtime emits one exact per-Case evaluation envelope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.ifeval.case_grade import (
    CASE_GRADE_SCHEMA,
    CHECK_SCHEMA,
)
from screamingface_engine.benchmarks.ifeval.definition import (
    CASE_GRADE_ROUTE,
    CHECK_ROUTE,
    IFEVAL,
    ROUTE_PREFIX,
)
from screamingface_engine.benchmarks.ifeval.runtime import install
from url4 import RelExpr, Text, expr, render, src
from url4.peer.server import Url4Node


def _assets(root: Path) -> None:
    (root / "instructions").mkdir(parents=True)
    (root / "cases.json").write_text(
        '[{"id":1,"input":"Describe tea without commas."}]', encoding="utf-8"
    )
    (root / "instructions" / "1.json").write_text(
        json.dumps(
            {
                "key": 1,
                "prompt": "Describe tea without commas.",
                "instruction_id_list": ["punctuation:no_comma"],
                "kwargs": [{}],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_runtime_packs_ordered_attempts_into_one_case_evaluation(tmp_path: Path) -> None:
    node = Url4Node("test")
    install(node, tmp_path)
    record = {
        "schema": CHECK_SCHEMA,
        "case_id": 1,
        "attempt": 1,
        "valid": True,
        "answer": "A compliant answer",
        "refusal": None,
        "finish_reason": "stop",
        "instruction_id_list": ["punctuation:no_comma"],
        "descriptions": ["Do not use commas."],
        "strict": [True],
        "loose": [True],
        "violations": [],
    }
    payload = json.dumps({"attempt_1": json.dumps(record)})
    expression = expr(
        src(Text(payload), name="payload", weight=0.0),
        src(
            RelExpr(
                path=f"{ROUTE_PREFIX}/case-evaluation",
                context="$payload",
                intent=Text("1"),
            ),
            name="case_evaluation",
            weight=0.0,
        ),
        intent=Text("$case_evaluation"),
    )

    result = json.loads((await node.evaluate(render(expression))).text)

    assert result == {
        "schema": CASE_GRADE_SCHEMA,
        "case_id": 1,
        "attempts": [record],
    }


@pytest.mark.asyncio
async def test_runtime_grades_exact_refusal_text_through_the_normal_checker(
    tmp_path: Path,
) -> None:
    _assets(tmp_path)
    node = Url4Node("test")
    install(node, tmp_path)
    exact = "I cannot comply."
    expression = expr(
        src(
            Text(encode_candidate_invocation("", "content_filter", exact)),
            name="candidate_result",
            weight=0.0,
        ),
        src(
            RelExpr(path=CHECK_ROUTE, context="$candidate_result", intent=Text("1:1")),
            name="record",
            weight=0.0,
        ),
        intent=Text("$record"),
    )

    record = json.loads((await node.evaluate(render(expression))).text)

    assert record["answer"] == exact
    assert record["refusal"] == exact
    assert record["finish_reason"] == "content_filter"
    assert record["strict"] == [True]


def test_canonical_resource_packs_the_check_before_aggregation() -> None:
    url4 = IFEVAL.resource(1)["url4"]

    assert isinstance(url4, str)
    assert url4.count(CASE_GRADE_ROUTE) == 1


def test_canonical_ifeval_reproduces_the_paper_protocol() -> None:
    # One Candidate invocation, one check, one aggregation — the protocol of
    # Zhou et al. (arXiv:2311.07911), so scores compare to published results.
    resource = IFEVAL.resource(1)
    url4 = resource["url4"]
    assert isinstance(url4, str)

    assert url4.count("/candidate") == 1
    assert url4.count(CHECK_ROUTE) == 1
    assert "!'aggregate:1'" in url4
