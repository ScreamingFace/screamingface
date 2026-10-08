"""Attempts per Case on the SDK side (OME-1458, PR 3 of 7).

FEATURE: a Benchmark that declares N Attempts asks each Case N times and marks a Check met
if any Attempt met it. The Engine sends every Attempt in an `attempts` list on the Case
Result; the SDK must know the key BEFORE any Engine emits it (its decoder refuses unknown
keys), bill each Attempt's model calls exactly once, say on the report how many Attempts
matched, and show "any of N Attempts" in the catalogue.

INVARIANT: a Benchmark without Attempts never sends the key, and its Case Result, report.json
and report card stay byte-identical.

The example used throughout: the Case "What is 6 times 7?"; Attempt 1 answers 41 (score 0),
Attempt 2 answers 42 (score 1), so the Case shows 42 and scores 1.0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from test_accounting_breakdown import accounting, replace
from test_report_panel import body
from test_report_panel import candidate as panel_candidate
from test_report_panel import report as panel_report

import screamingface as sf
from screamingface._engine.catalog_contract import _benchmark_entry
from screamingface._evaluation.results import _case_result
from screamingface._ui.cards import benchmark_card_html, benchmarks_rows_html
from screamingface._ui.report_view import _attempt_badges_html, _attempts_html, report_html
from screamingface.accounting import member_usage
from screamingface.case_result import CaseAttempt, CaseOperation
from screamingface.errors import ExecutionError


def _grade(score: float) -> sf.CaseGrade:
    """A one-Check exact-match grade: met at 1.0, unmet at 0.0."""

    check = sf.Check(
        type="exact_match",
        id="1",
        label="matches the target",
        outcome="MET" if score == 1.0 else "UNMET",
        score=score,
        evidence=(),
    )
    return sf.CaseGrade(method="inspect_scorer", score=score, metrics={}, checks=(check,))


def _attempt(number: int, output: str, score: float, **changes: Any) -> CaseAttempt:
    """One scored Attempt, the way the decoder builds it."""

    return CaseAttempt(
        attempt=number,
        status="scored",
        output=output,
        finish_reason="stop",
        refusal=None,
        grade=_grade(score),
        failures=(),
        **changes,
    )


def _failed_attempt(number: int) -> CaseAttempt:
    """An Attempt whose Candidate Invocation failed: no answer, no grade, one failure."""

    return CaseAttempt(
        attempt=number,
        status="failed",
        output=None,
        finish_reason=None,
        refusal=None,
        grade=None,
        failures=(
            sf.Failure(
                stage="candidate",
                code="model_empty_content",
                message="the model returned no text",
                case_id=1,
            ),
        ),
    )


def _case(attempts: tuple[CaseAttempt, ...] | None, **changes: Any) -> sf.CaseResult:
    """The Case "What is 6 times 7?" showing 42, folded to 1.0, with the given Attempts."""

    fields: dict[str, Any] = {
        "case_id": 1,
        "input": "What is 6 times 7?",
        "output": "42",
        "finish_reason": "stop",
        "grade": _grade(1.0),
        "failures": (),
        "metadata": {},
        "attempts": attempts,
    }
    return sf.CaseResult(**(fields | changes))


_TWO_ATTEMPTS: tuple[CaseAttempt, ...] = (_attempt(1, "41", 0.0), _attempt(2, "42", 1.0))


def _wire_attempt(number: int, output: str, score: float, **extra: Any) -> dict[str, Any]:
    """One Attempt exactly as the Engine's wire sends it, plus any extra keys."""

    return {**_attempt(number, output, score).to_dict(), **extra}


def _wire_case(**extra: Any) -> dict[str, Any]:
    """A Case Result exactly as the Engine's wire sends it, plus any extra keys."""

    return {**_case(None).to_dict(), **extra}


# --- sf.CaseResult and CaseAttempt ------------------------------------------------------


def test_a_case_result_without_attempts_is_unchanged() -> None:
    # INVARIANT: absence stays absence — every existing report exports byte-identically.
    plain = _case(None)

    assert plain.attempts is None
    assert "attempts" not in plain.to_dict()


def test_case_attempts_keep_their_order_and_grades() -> None:
    folded = _case(_TWO_ATTEMPTS)

    assert folded.attempts is not None
    assert [attempt.output for attempt in folded.attempts] == ["41", "42"]
    assert [attempt.matched for attempt in folded.attempts] == [False, True]
    exported = cast(list[dict[str, Any]], folded.to_dict()["attempts"])
    assert [item["attempt"] for item in exported] == [1, 2]


def test_attempt_numbers_must_run_from_one_without_gaps() -> None:
    with pytest.raises(ValueError, match="numbered 1..N"):
        _case((_attempt(1, "41", 0.0), _attempt(3, "42", 1.0)))


def test_a_single_attempt_list_is_refused() -> None:
    # WHY: one Attempt is spelled by absence, so a report has one shape per meaning.
    with pytest.raises(ValueError, match="N of at least 2"):
        _case((_attempt(1, "42", 1.0),))


def test_a_scored_attempt_without_a_grade_is_refused() -> None:
    # WHY: each Attempt obeys the Case Result's outcome rules, checked against this Case.
    ungraded = replace(_attempt(2, "42", 1.0), grade=None)
    with pytest.raises(ValueError, match="status 'scored'"):
        _case((_attempt(1, "41", 0.0), ungraded))


def test_case_level_operations_beside_attempts_are_refused() -> None:
    # WHY: each Attempt carries its own cost records; a Case-level copy would bill twice.
    with pytest.raises(ValueError, match="live on each Attempt"):
        _case(_TWO_ATTEMPTS, operations=(CaseOperation("op", "42", "stop", accounting()),))


# --- decoding the Engine's wire ---------------------------------------------------------


def test_case_result_decodes_an_optional_attempts_key() -> None:
    wire = _wire_case(attempts=[_wire_attempt(1, "41", 0.0), _wire_attempt(2, "42", 1.0)])

    decoded = _case_result(wire)

    assert decoded.attempts is not None
    assert [attempt.output for attempt in decoded.attempts] == ["41", "42"]
    assert decoded.to_dict() == wire
    assert _case_result(_wire_case()).attempts is None


def test_an_unknown_key_inside_an_attempt_is_refused() -> None:
    # WHY: strict decoding inside the list too — a newer Engine's field is a loud upgrade
    # signal, never silently dropped.
    wire = _wire_case(attempts=[_wire_attempt(1, "41", 0.0), _wire_attempt(2, "42", 1.0, seed=7)])

    with pytest.raises(ExecutionError, match="unsupported field 'seed'"):
        _case_result(wire)


def test_attempt_operations_decode_and_round_trip() -> None:
    operation: dict[str, Any] = CaseOperation("op", "42", "stop", accounting()).to_dict()
    wire = _wire_case(
        attempts=[
            _wire_attempt(1, "41", 0.0, operations=[{**operation, "output": "41"}]),
            _wire_attempt(2, "42", 1.0, operations=[operation]),
        ]
    )

    decoded = _case_result(wire)

    assert decoded.to_dict() == wire


# --- billing every Attempt exactly once -------------------------------------------------


def _billed_candidate(cost_usd: str) -> sf.CandidateResult:
    """A one-Case Candidate whose two Attempts each made one call costing $0.1."""

    attempts: tuple[CaseAttempt, ...] = (
        _attempt(1, "41", 0.0, operations=(CaseOperation("op", "41", "stop", accounting()),)),
        _attempt(2, "42", 1.0, operations=(CaseOperation("op", "42", "stop", accounting()),)),
    )
    value = panel_candidate("Example", 1.0, cases=(_case(attempts),))
    return replace(value, usage=sf.Usage(cost_usd=cost_usd), run_cost_status=None)


def test_a_case_with_attempts_is_billed_once_per_attempt() -> None:
    view = _billed_candidate("0.2").accounting

    # Two Attempts x one call x $0.1, and no "duplicate accounting operation" refusal.
    assert view.consistent
    assert view.by_stage["generation"].calls == 2
    assert view.by_case[1].usage.cost_usd == Decimal("0.2")
    assert view.unattributed_cost_usd == Decimal("0")


def test_member_usage_sums_every_attempt() -> None:
    usage = member_usage(_billed_candidate("0.2").cases, "op")

    assert usage is not None
    assert usage.cost_usd == Decimal("0.2")


# --- the report pane --------------------------------------------------------------------


def _pane(case: sf.CaseResult) -> str:
    """The report card's markup for one Candidate holding this one Case."""

    return body(report_html(panel_report(panel_candidate("a", 1.0, cases=(case,)))))


def test_the_case_pane_says_how_many_attempts_matched() -> None:
    html = _pane(_case(_TWO_ATTEMPTS))

    assert "1 of 2 Attempts matched" in html
    assert "Attempts failed" not in html


def test_a_failed_attempt_is_counted_on_the_pane() -> None:
    html = _pane(_case((_failed_attempt(1), _attempt(2, "42", 1.0))))

    assert "1 of 2 Attempts matched" in html
    assert "1 of 2 Attempts failed" in html


def test_each_attempt_answer_is_listed_under_the_case() -> None:
    html = _pane(_case(_TWO_ATTEMPTS))

    assert "Attempt 1 · score 0" in html
    assert "Attempt 2 · score 1" in html
    assert html.index(">41<") < html.index("Attempt 2 · score 1")


def test_a_case_without_attempts_renders_byte_identical() -> None:
    # INVARIANT: both Attempt fragments are empty for an ordinary Case, so its pane is the
    # markup it was before Attempts existed; nothing about Attempts reaches the page.
    plain = _case(None)

    assert _attempt_badges_html(plain) == ""
    assert _attempts_html(plain) == ""
    assert "Attempt" not in _pane(plain)


# --- the catalogue ----------------------------------------------------------------------


def _catalogue_entry(**extra: Any) -> dict[str, Any]:
    """One catalogue entry as the Engine serves it, plus any extra keys."""

    return {
        "object": "benchmark",
        "id": "arc_like",
        "title": "ARC-like",
        "description": "abstract reasoning grids",
        "revision": "r1",
        "case_count": 120,
        **extra,
    }


def _benchmark(entry: dict[str, Any]) -> sf.Benchmark:
    """The public Benchmark the catalogue entry becomes."""

    from screamingface._engine.catalog import _benchmark as to_benchmark

    return to_benchmark(_benchmark_entry(entry))


def test_the_catalogue_shows_any_of_n_attempts() -> None:
    benchmark = _benchmark(_catalogue_entry(attempts=2))

    assert benchmark.attempts == 2
    assert "any of 2 Attempts" in benchmarks_rows_html((benchmark,))
    assert "2 Candidate Invocations per Case" in benchmark_card_html(benchmark)


def test_a_catalogue_entry_without_attempts_means_one_and_shows_nothing() -> None:
    benchmark = _benchmark(_catalogue_entry())

    assert benchmark.attempts == 1
    assert "Attempts" not in benchmarks_rows_html((benchmark,))
    assert "Attempts" not in benchmark_card_html(benchmark)


def test_a_malformed_attempts_value_is_a_catalogue_defect() -> None:
    with pytest.raises(Exception, match="attempts must be a positive integer"):
        _benchmark_entry(_catalogue_entry(attempts=True))
