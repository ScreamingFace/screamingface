"""Read the per-Case fan-out's collected case grades back and file each one under its Case id.

A benchmark run is one url4 expression; every case in it produces one case grade. The engine fans
out over the selected cases, and each case comes back as a case grade holding the candidate's answer
plus the judge's verdicts, or an error where either step failed. The aggregate step is the part
that reads all those case grades back: decode the collected array, index case grades by case id,
notice an outer error (the whole fan-out branch failed), and pull the value out of each case grade.
Think of it as collecting the exam scripts from the hall and sorting them by student
number before any marking starts.

WHICH fan-out — the repo has three, nested, and every other mention names its axis
(`ensemble/policy.py` says "member fan-out"; `healthbench/variant.py` says "fan out one judge
task per rubric item"). This module reads the OUTERMOST one and only that:

    per-Case fan-out    one branch per selected Case          ← THIS MODULE reads it
      member fan-out    an ensemble Candidate's member models — runs INSIDE one Candidate
                        invocation and is collapsed into one answer before a case grade exists;
                        its attribution rides opaquely in the case grade's `operations` field
      judge fan-out     one judge call per rubric item        — already finished and nested
                        inside the case grade as `rubric_evaluations`

So by the time a case grade reaches this module the marking has happened and is stapled inside
the script. `rubric_evaluations` is never read here; the benchmark's `grade_case` reads it.

FEATURE: one shared grading code per benchmark (OME-1024); this module is the second extraction
(OME-1039 took the failure ladder) — the case grade reader gdpval and healthbench duplicated
near byte-identically after the two-week-old fork.

The stages, in execution order:

    Stage 1  decode the collected array           → "case grades are not JSON" / "must be an array"
    Stage 2  guard the count against the roll call → more case grades than Cases aborts
    Stage 3  per position, unwrap the case grade value    → a case grade may arrive double-encoded
    Stage 4  outer error?  identified → it IS that Case's case grade
                           anonymous  → retained as an orphan against that position
    Stage 5  otherwise decode the envelope         → grading error, or the benchmark-decoded case
    grade

Worked example — three Cases selected, `case_ids = (1, 2, 3)`:

    case grades[0] = a valid envelope for Case 1        → CaseGradeIndex.case_grades[1]
    case grades[1] = {"error": {...}}   (no case_id)    → CaseGradeIndex.collected_errors[2]
    case grades[2] = an envelope whose grading errored  → CaseGradeIndex.grading_failures[3]

Case 2 ends with no case grade at all, so the grader reports it as missing — and the orphan error
retained above it is what tells the reader *why*. On the shared grading code's default missing-case
step, the orphan's code (say `model_token_cap`) becomes the Case's failure code; a Case with no
orphan, or an orphan naming no code, reads as `missing_case_row`. Benchmarks that own their
missing-case step (IFEval, DRACO) spell it their own way.

INVARIANT: the case grade is an OPAQUE benchmark-owned envelope. This module files it and never
looks inside, so nothing here can freeze "a candidate's answer is text". The kind taxonomy is
OME-1103's decision; the seam that opens the envelope is OME-1097's `grade_case`.

INVARIANT: `case_ids` is the authoritative roll call and position is identity. A case grade that
claims a Case other than the one selected at its position aborts the run — scoring the
wrong Case is worse than reporting a failed one.

INVARIANT: a collected error is never dropped. An `on_error=collect` case grade loses its Case
identity, so it cannot be indexed; it is retained as an orphan and attached to the position
it arrived at, so the report names the cause and not just the symptom (exactly what was
missing in the first live smoke run).

INVARIANT: failure wording stays benchmark-owned. `benchmark_label` and `error_type` are
injected so each benchmark raises its own class with its own text — the extraction moves logic,
never messages.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import SelectedCase
from screamingface_engine.benchmarks.graded_answer import (
    GradedAnswer,
    case_attempts,
    graded_answer,
    graded_answer_matches,
)


@dataclass(frozen=True, slots=True)
class CaseGradeIndex:
    """One per-Case fan-out's case grades, split by what each position turned out to be.

    Attributes:
        case_grades: Case id → the benchmark-decoded evaluation envelope, opaque to the shared
        grading code. Also
            holds an identified error case, which IS that Case's case grade.
        collected_errors: Case id → the anonymous `on_error=collect` payloads that arrived
            at that position, retained so a missing case can name its cause.
        grading_failures: Case id → the preserved Candidate answer plus the grading error,
            for a Case whose Candidate answered but whose grading step failed.
        attempts: Case id → that Case's per-Attempt rows, in Attempt order, for a Benchmark
            that asks each Case several times (OME-1458). Each row is still opaque: the
            marking room files it with this same reader, one Attempt at a time.
    """

    case_grades: dict[int, dict[str, Any]]
    collected_errors: dict[int, list[dict[str, Any]]]
    grading_failures: dict[int, GradedAnswer]
    attempts: dict[int, list[object]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseGradeReader:
    """One benchmark's case grade reader — the shared reading steps bound to its own names.

    Each benchmark constructs one module-level instance. Only three things differ between the
    benchmarks, and all three are here:

    Attributes:
        benchmark_label: the benchmark's display name as it appears in this module's two
            decode error messages ("GDPval case grades are not JSON"). Display text, NOT an
            identity — two Benchmarks (`healthbench-worst30`, `healthbench-professional`)
            share the one label "HealthBench", so this is deliberately not `benchmark_id`.
        error_type: the benchmark's own `AggregateError`. Injected rather than shared so a
            test asserting one benchmark raised keeps failing when the other one does.
        decode_case_grade: the benchmark's envelope validator, the only authority on its
            own schema. Called as `(grading, expected_case_id) -> decoded case grade`; it raises
            `ValueError`/`TypeError`, which this module wraps with the case grade's position.
        claim_anonymous_errors: when True an anonymous `on_error=collect` case grade is ADOPTED
            as the case grade of the Case selected at its position, instead of being retained
            as an orphan cause. WHY (OME-1100): draco's fan-out emits anonymous error
            case grades and its pinned results report them as candidate-stage failures OF that
            Case — position is identity, so the adoption is sound for any benchmark that
            opts in.
    """

    benchmark_label: str
    error_type: type[Exception]
    decode_case_grade: Callable[[object, int], dict[str, Any]]
    claim_anonymous_errors: bool = False

    def index(self, raw_case_grades: str, case_ids: tuple[int, ...]) -> CaseGradeIndex:
        """Sort one per-Case fan-out's collected case grades into the three piles above.

        Args:
            raw_case_grades: the collected array as JSON text, in selected order.
            case_ids: the Cases this run selected — the authoritative roll call, and the
                identity of each position.

        Returns:
            The `CaseGradeIndex`. A selected Case absent from all three piles simply had no case
            grade; the grader reports that per Case, so nothing vanishes from the roll call.

        Raises:
            `error_type`: the payload, a case grade, or a case grade's claimed identity is unusable.
            Every such abort happens BEFORE any scoring, so a corrupt per-Case fan-out can never
            become a quietly wrong score.
        """

        # Stage 1-2 — decode the array and check it against the roll call.
        rows: list[Any] = self._decoded_case_grades(raw_case_grades)
        if len(rows) > len(case_ids):
            raise self.error_type(
                f"aggregate received {len(rows)} rows for {len(case_ids)} selected Cases"
            )
        index = CaseGradeIndex(case_grades={}, collected_errors={}, grading_failures={})
        # Stage 3-5 — position IS identity: case grade i belongs to the Case selected at i.
        for position, entry in enumerate(rows):
            self._file_case_grade(entry, position, case_ids[position], index)
        return index

    def _decoded_case_grades(self, raw: str) -> list[Any]:
        """Stage 1 — the collected array, still opaque, one entry per Case that ran."""

        try:
            decoded: object = json.loads(raw or "")
        except ValueError as exc:
            raise self.error_type(f"{self.benchmark_label} rows are not JSON: {exc}") from None
        if not isinstance(decoded, list):
            raise self.error_type(f"{self.benchmark_label} rows must be a JSON array")
        return decoded

    def _file_case_grade(
        self,
        entry: object,
        position: int,
        expected_case_id: int,
        index: CaseGradeIndex,
    ) -> None:
        """Stages 3-5 — unwrap one case grade, then file it as an error, a failure, or a grade."""

        row: Mapping[str, Any] = self._case_grade_value(entry, position)
        if self._filed_outer_error(row, position, expected_case_id, index):
            return
        try:
            attempted: tuple[object, list[object]] | None = case_attempts(row)
            if attempted is not None:
                claimed, rows = attempted
                if claimed != expected_case_id and str(claimed) != str(expected_case_id):
                    raise ValueError(
                        f"Case attempts claim case_id {claimed!r}, "
                        f"but the selected Case is {expected_case_id!r}"
                    )
                index.attempts[expected_case_id] = rows
                return
            outcome: GradedAnswer = graded_answer(row)
            if not graded_answer_matches(outcome, expected_case_id):
                raise ValueError(
                    f"Case execution claims case_id {outcome.case_id!r}, "
                    f"but the selected Case is {expected_case_id!r}"
                )
            if outcome.error is not None:
                index.grading_failures[expected_case_id] = outcome
            else:
                index.case_grades[expected_case_id] = self.decode_case_grade(
                    outcome.grading, expected_case_id
                )
        except (TypeError, ValueError) as exc:
            raise self.error_type(f"Case result at position {position} is invalid: {exc}") from None

    def _case_grade_value(self, entry: object, position: int) -> Mapping[str, Any]:
        """Stage 3 — url4 hands some case grades back as JSON text rather than as objects."""

        try:
            row: object = json.loads(entry) if isinstance(entry, str) else entry
        except ValueError as exc:
            raise self.error_type(
                f"Case result at position {position} is not JSON: {exc}"
            ) from None
        if not isinstance(row, Mapping):
            raise self.error_type(f"Case result at position {position} must be an object")
        return row

    def _filed_outer_error(
        self,
        row: Mapping[str, Any],
        position: int,
        expected_case_id: int,
        index: CaseGradeIndex,
    ) -> bool:
        """Stage 4 — this Case's whole branch failed; True when the case grade was filed here."""

        error: object = row.get("error")
        if error is None:
            return False
        if not isinstance(error, Mapping):
            raise self.error_type(f"Case result at position {position} has an invalid error")
        claimed: object = row.get("case_id")
        if claimed is not None and claimed != expected_case_id:
            raise self.error_type(
                f"Case result at position {position} claims case_id {claimed}, "
                f"but the selected Case is {expected_case_id}"
            )
        if claimed is None and not self.claim_anonymous_errors:
            # WHY: an anonymous error cannot be indexed, so it is retained against the
            # position it arrived at — the grader attaches it to the Case that ends up
            # with no case grade, which is how the symptom keeps its cause.
            index.collected_errors.setdefault(expected_case_id, []).append(dict(row))
        else:
            index.case_grades[expected_case_id] = dict(row)
        return True


def read_selected_cases(
    root: Path,
    case_ids: tuple[int, ...],
    *,
    benchmark_label: str,
    error_type: type[Exception],
) -> list[SelectedCase]:
    """Read the roll call from the prepared ``cases.json``, in selected order.

    The same benchmark-varying bits as `CaseGradeReader` are injected — the label for error
    wording and the benchmark's own error class (OME-1097 moved this reader in from the
    per-benchmark aggregates).
    """

    try:
        decoded: object = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise error_type(f"{benchmark_label} cases are unavailable: {exc}") from None
    if not isinstance(decoded, list):
        raise error_type(f"{benchmark_label} cases must be a JSON array")
    by_id: dict[int, Mapping[str, Any]] = {
        row_id: row
        for row in decoded
        if isinstance(row, Mapping)
        and isinstance((row_id := row.get("id")), int)
        and not isinstance(row_id, bool)
    }
    selected: list[SelectedCase] = []
    for case_id in case_ids:
        row: Mapping[str, Any] | None = by_id.get(case_id)
        input_value: object = row.get("input") if isinstance(row, Mapping) else None
        if not isinstance(input_value, str) or not input_value.strip():
            raise error_type(f"{benchmark_label} Case {case_id} has no public input")
        selected.append(SelectedCase(case_id=case_id, input=input_value, metadata={}))
    return selected


__all__ = ["CaseGradeIndex", "CaseGradeReader", "read_selected_cases"]
