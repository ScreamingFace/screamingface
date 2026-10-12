"""The abstain mark rides every benchmark's per-Case record to the grading room (E4a).

FEATURE: a Candidate Invocation marked ``abstained`` keeps that fact through the check record,
the Case Evaluation envelope and the hoisted row, as ``candidate_abstained`` (OME-1289).
STORY: as the shared grading code, I read the Candidate's mark off the row the benchmark filed,
without knowing which benchmark filed it.
INVARIANT defended: the record key is ``candidate_abstained`` and is written only when true,
so it never shares a key with a benchmark's own ``abstained`` verdict, and a record with no
mark is byte for byte what it was.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from test_healthbench_aggregate import _case_row, _grading
from test_ifeval_case_evaluation_route import _assets as _ifeval_assets

from screamingface_engine.benchmarks.case_records import build_case_record
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.grading_endpoints import CandidateAnswer, candidate_answer
from screamingface_engine.benchmarks.healthbench.case_grade import decode_case_grade
from screamingface_engine.benchmarks.ifeval import grade as ifeval_grade
from screamingface_engine.benchmarks.ifeval.case_grade import build_case_grade as ifeval_case_grade
from screamingface_engine.benchmarks.ifeval.definition import CHECK_ROUTE
from screamingface_engine.benchmarks.ifeval.runtime import install as install_ifeval_runtime
from screamingface_engine.benchmarks.medxpert import aggregate as medxpert_aggregate
from screamingface_engine.benchmarks.medxpert.case_grade import (
    CHECK_SCHEMA as MEDXPERT_CHECK_SCHEMA,
)
from screamingface_engine.benchmarks.medxpert.case_grade import (
    build_case_grade as medxpert_case_grade,
)
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import _candidate_fields
from screamingface_engine.benchmarks.shared_grading.serving import candidate_record
from url4 import RelExpr, Text, expr, render, src
from url4.peer.server import Url4Node

_ABST = encode_candidate_invocation("", "stop", None, abstained=True)
_PLAIN = encode_candidate_invocation("a plain answer", "stop", None)
_CASES = json.dumps([{"id": 1, "input": "the question"}])


def _build(reply: str) -> dict[str, object]:
    return build_case_record(
        _CASES, case_id=1, candidate=candidate_answer(reply), schema="s", benchmark="b"
    )


def test_the_shared_case_record_marks_only_an_abstained_candidate() -> None:
    assert _build(_ABST).get("candidate_abstained") is True
    assert "candidate_abstained" not in _build(_PLAIN)
    marked = CandidateAnswer("completed", "", "", "stop", None, None, abstained=True)
    assert candidate_record(
        marked, schema="s", case_id=1, verdict={"abstained": False}, tail={}
    ) == {
        "schema": "s",
        "case_id": 1,
        "attempt": 1,
        "abstained": False,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
        "candidate_abstained": True,
    }
    assert "candidate_abstained" not in candidate_record(
        candidate_answer(_PLAIN), schema="s", case_id=1, verdict={}, tail={}
    )


async def _ifeval_record(tmp_path: Path, reply: str) -> dict[str, Any]:
    _ifeval_assets(tmp_path)
    node = Url4Node("test")
    install_ifeval_runtime(node, tmp_path)
    expression = expr(
        src(Text(reply), name="candidate_result", weight=0.0),
        src(
            RelExpr(path=CHECK_ROUTE, context="$candidate_result", intent=Text("1:1")),
            name="record",
            weight=0.0,
        ),
        intent=Text("$record"),
    )
    record = json.loads((await node.evaluate(render(expression))).text)
    assert isinstance(record, dict)
    return record


def _medxpert_record(reply: str) -> dict[str, Any]:
    """The record ``medxpert.runtime._check`` builds, through the same ``candidate_record``."""
    return candidate_record(
        candidate_answer(reply),
        schema=MEDXPERT_CHECK_SCHEMA,
        case_id=1,
        verdict={"answer": "", "answered": False},
        tail={"commit_output": "", "reasoning": ""},
    )


def _hoisted(row: dict[str, Any]) -> dict[str, Any]:
    case = row["case"]
    assert isinstance(case, dict)
    return case


async def _hoisted_row(family: str, root: Path, reply: str) -> dict[str, Any]:
    """The row one family's decoder hoists from the real check record for ``reply``."""
    if family == "ifeval":
        record = await _ifeval_record(root, reply)
        specs = {1: {"instruction_id_list": ["punctuation:no_comma"]}}
        return ifeval_grade._decode(specs)(ifeval_case_grade(1, [record]), 1)
    record = _medxpert_record(reply)
    return medxpert_aggregate._decode(medxpert_case_grade(1, [record]), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["ifeval", "medxpert"])
async def test_a_marked_record_survives_its_hoist(family: str, tmp_path: Path) -> None:
    """A hoist that forgets the mark would silently grade an abstained Case as answered."""
    marked = await _hoisted_row(family, tmp_path / "marked", _ABST)
    plain = await _hoisted_row(family, tmp_path / "plain", _PLAIN)

    assert _hoisted(marked).get("candidate_abstained") is True
    assert _candidate_fields(marked).abstained is True
    assert "candidate_abstained" not in _hoisted(plain)
    assert _candidate_fields(plain).abstained is False


def _accepted(grading: dict[str, Any]) -> bool:
    try:
        decode_case_grade(grading, 1)
    except ValueError:
        return False
    return True


def test_healthbench_accepts_the_mark_on_its_case_record_and_nothing_else() -> None:
    grading = _grading(_case_row(1, {1: True}))
    assert _accepted(grading)
    marked = copy.deepcopy(grading)
    marked["case"]["output"] = marked["case"]["answer"] = ""
    marked["case"]["candidate_abstained"] = True

    assert _accepted(marked)
    marked["case"]["candidate_abstained"] = False
    assert not _accepted(marked)
    marked["case"]["candidate_abstained"] = "yes"
    assert not _accepted(marked)


def test_candidate_fields_read_the_mark_only_when_it_is_true() -> None:
    def fields(case: dict[str, Any]) -> Any:
        return _candidate_fields({"case": {"status": "completed", "output": "", **case}})

    assert fields({"candidate_abstained": True}).abstained is True
    assert fields({}).abstained is False
    assert fields({"candidate_abstained": "yes"}).abstained is False
    assert _candidate_fields(None).abstained is False
