"""OME-1458 — Attempts on the Engine's wire and on the Benchmark's cover sheet.

FEATURE: a Benchmark declares `attempts=N` on its `BenchmarkDeclaration`; its Case Results
carry an `attempts` list, one entry per Attempt.

INVARIANT: both are absent unless set — a Benchmark without Attempts publishes the same
catalogue entry, resource and Case Results, byte for byte, as before.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_request import CASE_ATTEMPT_PARAM
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_ROUTE,
    CaseAttempt,
    CaseGrade,
    CaseResult,
)
from screamingface_engine.benchmarks.definition import ATTEMPTS_KEY, Benchmark, BenchmarkDeclaration
from screamingface_engine.benchmarks.graded_answer import CASE_ATTEMPTS_ROUTE
from screamingface_engine.benchmarks.protocol import preserve_candidate_outcome
from url4 import RelExpr, Text, render

# parents[3] = apps/, so its parent is the monorepo root
_SDK_PACKAGE = Path(__file__).resolve().parents[3].parent / "packages" / "screamingface"
_SDK_RESULTS = _SDK_PACKAGE / "src" / "screamingface" / "_evaluation" / "results.py"
_SDK_VOCABULARY = _SDK_PACKAGE / "src" / "screamingface" / "_catalogue_vocabulary.py"


def _grade(score: float) -> CaseGrade:
    return CaseGrade(method="inspect_scorer", score=score, metrics={}, checks=[])


def _attempt(number: int, output: str, score: float) -> dict[str, Any]:
    return {
        "attempt": number,
        "status": "scored",
        "output": output,
        "finish_reason": "stop",
        "refusal": None,
        "grade": _grade(score),
        "failures": [],
    }


def _case(**overrides: Any) -> CaseResult:
    """Case 1, "What is 6 times 7?", showing 42 at 1.0, plus any overrides."""

    values: dict[str, Any] = {
        "status": "scored",
        "case_id": 1,
        "input": "What is 6 times 7?",
        "output": "42",
        "finish_reason": "stop",
        "refusal": None,
        "grade": _grade(1.0),
        "failures": [],
        "metadata": {},
    }
    values.update(overrides)
    return CaseResult(**values)


# --- the Case Result --------------------------------------------------------------------


def test_attempts_is_absent_from_the_payload_when_unset() -> None:
    assert "attempts" not in _case().model_dump()


def test_attempts_round_trip_in_order() -> None:
    case = _case(attempts=[_attempt(1, "41", 0.0), _attempt(2, "42", 1.0)])

    dumped: dict[str, Any] = case.model_dump()
    assert [item["output"] for item in dumped["attempts"]] == ["41", "42"]
    assert CaseResult.model_validate(dumped) == case


@pytest.mark.parametrize(
    "numbers", [[1], [1, 3], [2, 1], [0, 1]], ids=["one", "gap", "order", "zero"]
)
def test_attempt_numbers_run_from_one_with_at_least_two(numbers: list[int]) -> None:
    with pytest.raises(ValidationError):
        _case(attempts=[_attempt(number, "42", 1.0) for number in numbers])


def test_a_scored_attempt_without_a_grade_is_refused() -> None:
    ungraded: dict[str, Any] = {**_attempt(2, "42", 1.0), "grade": None}

    with pytest.raises(ValidationError, match="scored"):
        _case(attempts=[_attempt(1, "41", 0.0), ungraded])


def test_case_level_operations_beside_attempts_are_refused() -> None:
    operation: dict[str, Any] = {
        "operation_id": "op",
        "output": "42",
        "finish_reason": "stop",
        "accounting": None,
    }

    with pytest.raises(ValidationError, match="each attempt"):
        _case(attempts=[_attempt(1, "41", 0.0), _attempt(2, "42", 1.0)], operations=[operation])


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_a_case_attempt_has_the_keys_the_sdk_decodes() -> None:
    # INVARIANT: the SDK decoder refuses unknown keys, so the Engine's CaseAttempt and the
    # SDK's `_case_attempt` must list the same keys; whichever side drifts goes red here.
    tree = ast.parse(_SDK_RESULTS.read_text(encoding="utf-8"))
    decoder: ast.FunctionDef = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_case_attempt"
    )
    sdk_keys: set[str] = {
        item.value
        for call in ast.walk(decoder)
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_keys"
        for keyword in call.keywords
        if keyword.arg in {"required", "optional"}
        for item in ast.walk(keyword.value)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }

    assert sdk_keys == set(CaseAttempt.model_fields)


# --- the cover sheet --------------------------------------------------------------------


def _declaration(**overrides: Any) -> BenchmarkDeclaration:
    values: dict[str, Any] = {
        "failure_policy": "coverage_declare",
        "interaction": "single_shot",
        "difficulty": "hard",
    }
    values.update(overrides)
    return BenchmarkDeclaration(**values)


def test_attempts_defaults_to_one_and_stays_out_of_the_block() -> None:
    declaration = _declaration()

    assert declaration.attempts == 1
    assert declaration.as_block() == {
        "failure_policy": "coverage_declare",
        "interaction": "single_shot",
        "difficulty": "hard",
    }


def test_attempts_above_one_is_published_in_the_block() -> None:
    assert _declaration(attempts=2).as_block()[ATTEMPTS_KEY] == 2


@pytest.mark.parametrize("value", [0, -1, True, 2.0, "2"])
def test_attempts_below_one_or_not_an_int_is_refused(value: object) -> None:
    with pytest.raises(ValueError, match="attempts"):
        _declaration(attempts=value)


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_attempts_key_matches_the_sdk() -> None:
    tree = ast.parse(_SDK_VOCABULARY.read_text(encoding="utf-8"))
    sdk_key: object = next(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", "") == "ATTEMPTS_KEY"
        and isinstance(node.value, ast.Constant)
    )

    assert sdk_key == ATTEMPTS_KEY


# --- the cover sheet and the expression agree ------------------------------------------


def _asked_attempts(benchmark: Benchmark) -> int:
    """How many Attempts per Case the Benchmark's built expression really asks.

    1 when it never joins Attempts; otherwise the highest Attempt number the rendered URL4
    sends on a Candidate Invocation (Attempt 1 carries none).
    """

    rendered: str = render(benchmark.build(1))
    if CASE_ATTEMPTS_ROUTE not in rendered:
        return 1
    asked: int = 1
    while f"{CASE_ATTEMPT_PARAM}={asked + 1}" in rendered:
        asked += 1
    return asked


@pytest.mark.parametrize("benchmark", tuple(BUILTIN_BENCHMARKS), ids=lambda item: item.id)
def test_every_benchmark_asks_as_many_attempts_as_it_declares(benchmark: Benchmark) -> None:
    # INVARIANT: the cover sheet's `attempts` (the catalogue's "any of N Attempts", the
    # revision) and the expression's `preserve_candidate_outcome(attempts=)` are written in two
    # places by a Benchmark we build ourselves. If only the first says 2, the board publishes a
    # first-Attempt score under an any-of-2 label, silently (review finding on #1306).
    assert _asked_attempts(benchmark) == benchmark.declaration.attempts


def _probe(*, declared: int, asked: int) -> Benchmark:
    """A test-only Benchmark: its cover sheet says ``declared``, its expression asks ``asked``."""

    return Benchmark(
        id="attempts-probe",
        title="Attempts Probe",
        description="A structural probe; never served.",
        revision="attempts-probe-v1",
        case_count=1,
        build=lambda _selected: preserve_candidate_outcome(
            candidate_invocation=RelExpr(path=CANDIDATE_ROUTE, context="q", intent=Text("")),
            grading=RelExpr(path="/grade", context="$candidate_invocation", intent=Text("")),
            case_id="1",
            attempts=asked,
        ),
        declaration=_declaration(attempts=declared),
    )


def test_a_cover_sheet_the_expression_ignores_is_caught() -> None:
    # Stand-ins for the forgotten second number, and for both written: the check above
    # compares exactly these two counts.
    assert _asked_attempts(_probe(declared=2, asked=1)) == 1
    assert _asked_attempts(_probe(declared=2, asked=2)) == 2
    assert _asked_attempts(_probe(declared=3, asked=3)) == 3
