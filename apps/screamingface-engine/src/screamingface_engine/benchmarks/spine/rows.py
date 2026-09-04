"""Read the per-Case fan-out's collected rows back and file each one under its Case id.

Think of the exam hall at the end of a paper: the run fanned out over the selected Cases,
one script came back per Case, and this is the invigilator collecting the pile and sorting
it by student number. No marking happens here — a script is filed, or it is refused as
unreadable. Marking is `spine.grading.CaseGrader`.

WHAT "FAN-OUT" MEANS HERE — it is a url4 expression-graph word, not a scheduling one. A
benchmark run is ONE url4 expression; a fan-out is a node in that expression producing N
independent branches whose results collect back into an array. The branches are network
calls to the AI Gateway, not CPU work, so the width is a property of the EXPRESSION and
the bound on it is configured concurrency — never core count, never one Case per core.
(`schemas/openapi.py` puts it plainly: "one url4 expression is many gateway calls".)

WHICH fan-out — the repo has three, nested, and every other mention names its axis
(`ensemble/policy.py` says "member fan-out"; `healthbench/exam.py` says "fan out one judge
task per rubric item"). This module reads the OUTERMOST one and only that:

    per-Case fan-out    one branch per selected Case          ← THIS MODULE reads it
      member fan-out    an ensemble Candidate's member models — runs INSIDE one Candidate
                        invocation and is collapsed into one answer before a row exists;
                        its attribution rides opaquely in the row's `operations` field
      judge fan-out     one judge call per rubric item        — already finished and nested
                        inside the row as `rubric_evaluations`

So by the time a row reaches this module the marking has happened and is stapled inside
the script. `rubric_evaluations` is never read here; `CaseGrader`'s board hooks read it.

FEATURE: one grading spine per benchmark (OME-1024); this module is the second extraction
(OME-1039 took the failure ladder) — the row reader gdpval and healthbench duplicated
near byte-identically after the two-week-old fork.

The stages, in execution order:

    Stage 1  decode the collected array           → "rows are not JSON" / "must be an array"
    Stage 2  guard the count against the roll call → more rows than Cases aborts
    Stage 3  per position, unwrap the row value    → a row may arrive double-encoded
    Stage 4  outer error?  identified → it IS that Case's row
                           anonymous  → retained as an orphan against that position
    Stage 5  otherwise decode the envelope         → grading error, or the board-decoded row

Worked example — three Cases selected, `case_ids = (1, 2, 3)`:

    rows[0] = a valid envelope for Case 1        → RowIndex.rows[1]
    rows[1] = {"error": {...}}   (no case_id)    → RowIndex.collected_errors[2]
    rows[2] = an envelope whose grading errored  → RowIndex.grading_failures[3]

Case 2 ends with no row at all, so the grader reports it as `missing_case_row` — and the
orphan error retained above it is what tells the reader *why*.

INVARIANT: the row is an OPAQUE board-owned envelope. This module files it and never looks
inside, so nothing here can freeze "a candidate's answer is text". The kind taxonomy is
OME-1103's decision; the seam that opens the envelope is OME-1097's `grade_case`.

INVARIANT: `case_ids` is the authoritative roll call and position is identity. A row that
claims a Case other than the one selected at its position aborts the run — scoring the
wrong Case is worse than reporting a failed one.

INVARIANT: a collected error is never dropped. An `on_error=collect` row loses its Case
identity, so it cannot be indexed; it is retained as an orphan and attached to the position
it arrived at, so the report names the cause and not just the symptom (exactly what was
missing in the first live smoke run).

INVARIANT: failure wording stays board-owned. `benchmark_label` and `error_type` are
injected so each board raises its own class with its own text — the extraction moves logic,
never messages.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from screamingface_engine.benchmarks.case_execution import (
    CaseExecutionOutcome,
    case_execution_matches,
    case_execution_outcome,
)


@dataclass(frozen=True, slots=True)
class RowIndex:
    """One per-Case fan-out's rows, split by what each position turned out to be.

    Attributes:
        rows: Case id → the board-decoded evaluation envelope, opaque to the spine. Also
            holds an identified error row, which IS that Case's row.
        collected_errors: Case id → the anonymous `on_error=collect` payloads that arrived
            at that position, retained so a missing row can name its cause.
        grading_failures: Case id → the preserved Candidate answer plus the grading error,
            for a Case whose Candidate answered but whose grading step failed.
    """

    rows: dict[int, dict[str, Any]]
    collected_errors: dict[int, list[dict[str, Any]]]
    grading_failures: dict[int, CaseExecutionOutcome]


@dataclass(frozen=True, slots=True)
class RowReader:
    """One board's row reader — the shared reading steps bound to the board's own names.

    Each board constructs one module-level instance. Only three things differ between the
    boards, and all three are here:

    Attributes:
        benchmark_label: the board's display name as it appears in this module's two
            decode error messages ("GDPval rows are not JSON"). Display text, NOT an
            identity — two Benchmarks (`healthbench-worst30`, `healthbench-professional`)
            share the one label "HealthBench", so this is deliberately not `benchmark_id`.
        error_type: the board's own `AggregateError`. Injected rather than shared so a
            test asserting one board raised keeps failing when the other one does.
        decode_case_evaluation: the board's envelope validator, the only authority on its
            own schema. Called as `(grading, expected_case_id) -> decoded row`; it raises
            `ValueError`/`TypeError`, which this module wraps with the row's position.
    """

    benchmark_label: str
    error_type: type[Exception]
    decode_case_evaluation: Callable[[object, int], dict[str, Any]]

    def index(self, raw_rows: str, case_ids: tuple[int, ...]) -> RowIndex:
        """Sort one per-Case fan-out's collected rows into the three piles above.

        Args:
            raw_rows: the collected array as JSON text, in selected order.
            case_ids: the Cases this run selected — the authoritative roll call, and the
                identity of each position.

        Returns:
            The `RowIndex`. A selected Case absent from all three piles simply had no row;
            the grader reports that per Case, so nothing vanishes from the roll call.

        Raises:
            `error_type`: the payload, a row, or a row's claimed identity is unusable. Every
            such abort happens BEFORE any scoring, so a corrupt per-Case fan-out can never
            become a quietly wrong score.
        """

        # Stage 1-2 — decode the array and check it against the roll call.
        rows = self._decoded_rows(raw_rows)
        if len(rows) > len(case_ids):
            raise self.error_type(
                f"aggregate received {len(rows)} rows for {len(case_ids)} selected Cases"
            )
        index = RowIndex(rows={}, collected_errors={}, grading_failures={})
        # Stage 3-5 — position IS identity: row i belongs to the Case selected at i.
        for position, entry in enumerate(rows):
            self._file_row(entry, position, case_ids[position], index)
        return index

    def _decoded_rows(self, raw: str) -> list[Any]:
        """Stage 1 — the collected array, still opaque, one entry per Case that ran."""

        try:
            decoded = json.loads(raw or "")
        except ValueError as exc:
            raise self.error_type(f"{self.benchmark_label} rows are not JSON: {exc}") from None
        if not isinstance(decoded, list):
            raise self.error_type(f"{self.benchmark_label} rows must be a JSON array")
        return decoded

    def _file_row(
        self,
        entry: object,
        position: int,
        expected_case_id: int,
        index: RowIndex,
    ) -> None:
        """Stages 3-5 — unwrap one row, then file it as an error, a failure, or a row."""

        row = self._row_value(entry, position)
        if self._filed_outer_error(row, position, expected_case_id, index):
            return
        try:
            outcome = case_execution_outcome(row)
            if not case_execution_matches(outcome, expected_case_id):
                raise ValueError(
                    f"Case execution claims case_id {outcome.case_id!r}, "
                    f"but the selected Case is {expected_case_id!r}"
                )
            if outcome.error is not None:
                index.grading_failures[expected_case_id] = outcome
            else:
                index.rows[expected_case_id] = self.decode_case_evaluation(
                    outcome.grading, expected_case_id
                )
        except (TypeError, ValueError) as exc:
            raise self.error_type(f"Case result at position {position} is invalid: {exc}") from None

    def _row_value(self, entry: object, position: int) -> Mapping[str, Any]:
        """Stage 3 — url4 hands some rows back as JSON text rather than as objects."""

        try:
            row = json.loads(entry) if isinstance(entry, str) else entry
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
        index: RowIndex,
    ) -> bool:
        """Stage 4 — this Case's whole branch failed; True when the row was filed here."""

        error = row.get("error")
        if error is None:
            return False
        if not isinstance(error, Mapping):
            raise self.error_type(f"Case result at position {position} has an invalid error")
        claimed = row.get("case_id")
        if claimed is not None and claimed != expected_case_id:
            raise self.error_type(
                f"Case result at position {position} claims case_id {claimed}, "
                f"but the selected Case is {expected_case_id}"
            )
        if claimed is None:
            # WHY: an anonymous error cannot be indexed, so it is retained against the
            # position it arrived at — the grader attaches it to the Case that ends up
            # with no row, which is how the symptom keeps its cause.
            index.collected_errors.setdefault(expected_case_id, []).append(dict(row))
        else:
            index.rows[expected_case_id] = dict(row)
        return True


__all__ = ["RowIndex", "RowReader"]
