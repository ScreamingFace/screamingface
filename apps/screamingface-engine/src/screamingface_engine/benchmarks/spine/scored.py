"""The shared scored path — every rubric board's marking room, written once.

A benchmark run is an url4 expression that fans out one sub-call per Case — 100 exam
questions → 100 parallel candidate calls. It returns one row per Case (the graded paper),
and this module is the marking room that turns the pile into the exam result.
The only per-board step is ``grade_case`` — the one function every benchmark writes to
mark one script; everything around it (the roll call, the failure ladder, result
assembly, the exam-level reduction) is spine machinery a board author never sees.

The goal of this module is to have a shared grading pipeline (the "spine"), and each
benchmark only plugs in its own marking logic. Before this shared module, ``gdpval/grade.py``
and ``healthbench/grade.py`` each had their own copy of the same ~code: the loop that files
rows by case, runs the failure ladder, grades each case, and computes the final score.
The copies were almost character-for-character the same.
This is the path for any rubric-scored (LLM-as-judge) benchmark, present or future.

One aggregate call = marking one class's exam.
- Stage 1 — roll call. Get the class list: which Cases (questions/students) were selected
    for this run, in order. Say Cases [3, 7, 12].
- Stage 2 — sort the pile. The fan-out dumped back a pile of result rows in whatever order.
    RowReader files each row under its Case id, so "give me Case 7's paper" is a lookup.
- Stage 3 — the ladder: decide if each paper is even gradeable. Before marking, check each
    Case against a list of broken states, worst first. First match wins, and the Case becomes
    a visible failure in the results — never silently dropped:
        - the grading step itself errored earlier → benchmark's own failure code
        - there's nothing to grade against (rubric asset missing) → missing_rubric_asset
        - no paper turned up for this student at all → missing_case_row, with the reason
          the row went missing attached
        - a paper turned up but it's an error report, not an answer → case_error
        - Example: Case 7's row is an error row → it gets a case_error result and skips Stage 4.
- Stage 4 — mark the survivors. For each Case that passed the ladder, call grade_case,
    the one function the benchmark author writes. Answer + rubric in, grade out.
    The hook can still fail a Case (e.g. the judge returned verdicts for only 3 of 5 rubric
    points → incomplete_verdicts), and the failure message text belongs to the benchmark,
    not the spine.
- Stage 5 — total the marks. Wrap each Case's outcome into a `CaseResult`, then compute the
    exam-level score with the shared scorer. The benchmark contributes exactly one thing
    here: its mean (how per-Case scores average into the headline number). Everything else —
    the metric names in the output — is fixed spine vocabulary, so every benchmark's
    report looks the same.

The key design point: Stages 1, 2, 3, 5 are identical for every benchmark (spine).
Only Stage 4's grade_case (plus failure wording and the mean) is per-benchmark.

INVARIANT (the hourglass waist): a ``GradeRequest`` carries only plain, serializable
data — kind-tagged payloads, the decoded row mapping, the board's grading material.
No ``Path``, no engine objects, no callbacks. Three consumers force this: an enclave
judge across a privacy boundary, the inspect_evals scorer shim, and agentic boards.

INVARIANT: failure codes and message texts stay byte-identical per board — wording is
board-supplied (gdpval says "criterion" where healthbench says "rubric item"); the
extraction moves logic, never words. The e2e goldens pin every failed Case's code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    PublicError,
    SelectedCase,
    failed_case_result,
    finalize_candidate_result,
    grading_failure_case_result,
    public_error,
    refusal_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.case_execution import CaseExecutionOutcome
from screamingface_engine.benchmarks.contract import CaseId, CaseResult
from screamingface_engine.benchmarks.spine.payloads import CasePayload, TextPayload
from screamingface_engine.benchmarks.spine.rows import RowIndex, RowReader


@dataclass(frozen=True, slots=True)
class GradeRequest:
    """Everything a board needs to mark one script — plain data, nothing else.

    Attributes:
        case_id: the Case being graded.
        input: what the Candidate was asked, as a kind-tagged payload.
        answer: what it answered, or ``None`` when no usable answer text exists
            (a refusal's text rides on the assembled result, not here).
        row: the board-decoded evaluation envelope — the judge's work is inside it.
        material: the board's grading material for this Case (rubric points today;
            a label or verifier command for later grading modes). Opaque to the spine.
    """

    case_id: CaseId
    input: CasePayload
    answer: CasePayload | None
    row: Mapping[str, Any]
    material: object


@dataclass(frozen=True, slots=True)
class CaseGradeOutcome:
    """One marked script, as a complete value — nothing else crosses back.

    ``failure_code`` names why an ungraded Case failed ("incomplete_verdicts",
    "no_positive_points"); the board's message table supplies its wording. A graded
    Case carries ``score`` and ``failure_code=None`` — never both.
    """

    # WHY Any, not int (OME-1100): draco's per-Case metric block carries floats,
    # None (an unobserved axis), and nested per-axis dicts — counting claims are a
    # board vocabulary, not a spine one.
    score: float | None
    metrics: Mapping[str, Any]
    checks: Sequence[Mapping[str, Any]]
    failure_code: str | None = None


#: The seam every benchmark implements: async because the call may be a network hop
#: (an enclave judge), data-only because nothing else crosses a privacy boundary.
type GradeCase = Callable[[GradeRequest], Awaitable[CaseGradeOutcome]]

#: A board-owned replacement for the whole missing-row CaseResult — called as
#: ``(selected, selected_index, orphan_errors_or_None)``. WHY the whole result and
#: not just the failure dict: ifeval publishes a missing-row Case with ``grade: None``
#: (no grade envelope at all), and its golden pins that shape byte-for-byte.
#: Returning ``None`` (OME-1100) files NOTHING for the Case, so the finalizer
#: materialises it as ``case_result_missing`` — draco's pinned missing-row shape.
type MissingRowResult = Callable[
    [SelectedCase, int, list[dict[str, Any]] | None], CaseResult | None
]

#: A board-owned replacement for the whole error-row CaseResult — called as
#: ``(selected, selected_index, row)`` where ``row`` carries the ``"error"`` payload.
#: WHY (OME-1100): draco publishes the UPSTREAM error's own code ("rate_limited",
#: "provider_error") on a candidate-stage failure with no grade envelope, where the
#: spine default publishes the fixed ``case_error`` code with an empty grade — the
#: e2e failure tapes pin draco's shape byte-for-byte.
type ErrorRowResult = Callable[[SelectedCase, int, Mapping[str, Any]], CaseResult]

#: A board-owned replacement for the whole missing-material CaseResult — called as
#: ``(selected, selected_index, row_or_None)`` when ``grading_material`` returned
#: ``None``. WHY (OME-1100): draco pins ``missing_case_rubric`` with a ``row_index``
#: and no grade envelope, with the Candidate's answer retained off the row.
type MissingMaterialResult = Callable[[SelectedCase, int, Mapping[str, Any] | None], CaseResult]

#: A board-owned replacement for the whole hook-failure CaseResult — called as
#: ``(selected, selected_index, row, outcome)`` when the board's ``grade_case``
#: returned a ``failure_code``. WHY (OME-1100): draco's incomplete Case keeps its
#: full zeroed metric block and its judge checks in the grade (audit material) with
#: a ``row_index`` failure, where the default assembly publishes empty metrics with
#: judged/expected counts.
type HookFailureResult = Callable[
    [SelectedCase, int, Mapping[str, Any], CaseGradeOutcome], CaseResult
]


class _Omitted:
    """Sentinel: the board's missing-row hook filed nothing for this Case.

    Distinct from ``None`` on the ladder, which means "the Case is gradeable".
    """


_OMITTED = _Omitted()


@dataclass(frozen=True, slots=True)
class ScoredPath:
    """One board's scored path — the shared stages bound to the board's own seam.

    Each board constructs one module-level instance. What a board still owns:

    Attributes:
        reader: the board's `RowReader` (its label, error class, envelope decoder).
        grade_case: the board's hook — the only per-board grading code.
        failure_messages: failure code → the public message shown for it. Wording is
            board voice; this path never invents text.
        method: the grade's published method label ("rubric" for the rubric boards,
            "deterministic" for ifeval).
        grading_failure_code: the board's code for "the grading step itself failed".
        grading_failure_message: its default public message.
        missing_row_result: optional board-owned builder for the WHOLE missing-row
            CaseResult (wording, codes, grade shape). ``None`` keeps the spine
            default (``missing_case_row`` with the orphan cause attached). WHY
            (OME-1101): ifeval's recorded golden pins its own collected-row wording
            (stage "grading", the diagnostic's code), and OME-981 owns the
            candidate-vs-grading boundary decision — the spine must not default it.
        error_row_result: optional board-owned builder for the WHOLE error-row
            CaseResult. A board that sets it also owns the rung's RANK: its error
            rows are reported before the material rung (draco reports a broken row
            over its own missing rubric). ``None`` keeps the ``case_error`` default.
        missing_material_result: optional board-owned builder for the WHOLE
            missing-material CaseResult. ``None`` keeps the ``missing_rubric_asset``
            default.
        hook_failure_result: optional board-owned builder for the WHOLE CaseResult
            of a hook-reported failure (``grade_case`` returned a ``failure_code``).
            ``None`` keeps the default assembly (empty metrics, judged/expected
            metadata).
        missing_material_code: the published failure code when a Case's grading
            material is unusable (the default missing-material rung only — a
            ``missing_material_result`` hook owns its whole shape). WHY board-named
            (OME-1149): the rubric boards say ``missing_rubric_asset``, but an MCQ
            board's material is its answer key — publishing a rubric-flavored code
            there would contradict its own message.
    """

    reader: RowReader
    grade_case: GradeCase
    failure_messages: Mapping[str, str]
    method: str
    grading_failure_code: str
    grading_failure_message: str
    missing_row_result: MissingRowResult | None = None
    error_row_result: ErrorRowResult | None = None
    missing_material_result: MissingMaterialResult | None = None
    hook_failure_result: HookFailureResult | None = None
    missing_material_code: str = "missing_rubric_asset"

    def aggregate(
        self,
        raw_rows: str,
        *,
        benchmark_id: str,
        benchmark_revision: str,
        selected_cases: Sequence[SelectedCase],
        grading_material: Callable[[int], object | None],
        scorer: Callable[[Sequence[CaseResult]], CandidateScore],
        case_metadata: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Mark every selected Case, then score the exam with the board's own scorer.

        Args:
            raw_rows: the collected array of Case execution rows, in selected order.
            benchmark_id: the board publishing this result.
            benchmark_revision: that board's revision, stamped into the result.
            selected_cases: the authoritative roll call, in selected order.
            grading_material: per-Case loader for the board's grading material;
                ``None`` marks the material unusable (``missing_material_code``).
            scorer: the exam-level reduction, the board's whole ``CandidateScore``
                builder. Rubric boards bind ``exam_scorer(mean)`` (fixed rubric
                vocabulary, mean the only choice); a non-rubric board (ifeval)
                supplies its published metric vocabulary here (OME-1101).
            case_metadata: optional per-Case loader for PUBLIC report metadata that
                does not ride the row (OME-1149: MedXpertQA's slice tags live in the
                private answer asset). Merged into the spine-assembled scored and
                failed results, so failure-mode analysis can group by the same axes;
                row-level grading failures and board-owned result hooks keep their
                own (pre-fold) shape.

        Returns:
            The Candidate result payload: every selected Case, its grade or its
            failure, the exam score, and the run's factual coverage.
        """

        # Stage 1-2 — roll call and row filing (position is identity; see rows.py).
        case_ids: tuple[int, ...] = tuple(int(selected.case_id) for selected in selected_cases)
        indexed: RowIndex = self.reader.index(raw_rows, case_ids)
        # Stage 3-4 — the hook is async (an enclave call is a network hop); the
        # surrounding url4 handler is sync.
        case_results: list[CaseResult] = _run_sync(
            self._case_results(selected_cases, indexed, grading_material, case_metadata)
        )
        # Stage 5 — fold the marks into the class results.
        return finalize_candidate_result(
            benchmark_id=benchmark_id,
            benchmark_revision=benchmark_revision,
            selected_cases=list(selected_cases),
            cases=case_results,
            scorer=scorer,
        ).as_payload()

    async def _case_results(
        self,
        selected_cases: Sequence[SelectedCase],
        indexed: RowIndex,
        grading_material: Callable[[int], object | None],
        case_metadata: Callable[[int], Mapping[str, Any]] | None,
    ) -> list[CaseResult]:
        # WHY sequential, not gather: selected order is publication order, and no
        # current hook overlaps I/O; concurrency semantics are a later, separate call.
        results: list[CaseResult | None] = [
            await self._case_result(selected, index, indexed, grading_material, case_metadata)
            for index, selected in enumerate(selected_cases)
        ]
        # An omitted Case (a missing-row hook returned None) files nothing; the
        # finalizer materialises it as case_result_missing, so nothing vanishes.
        return [result for result in results if result is not None]

    async def _case_result(
        self,
        selected_case: SelectedCase,
        selected_index: int,
        indexed: RowIndex,
        grading_material: Callable[[int], object | None],
        case_metadata: Callable[[int], Mapping[str, Any]] | None,
    ) -> CaseResult | None:
        case_id: int = int(selected_case.case_id)
        row: dict[str, Any] | None = indexed.rows.get(case_id)
        material: object | None = grading_material(case_id)
        extra_metadata: Mapping[str, Any] = case_metadata(case_id) if case_metadata else {}
        ladder: CaseResult | _Omitted | None = self._ladder_result(
            selected_case, selected_index, indexed, row, material, extra_metadata
        )
        if isinstance(ladder, _Omitted):
            return None
        result: CaseResult | None = ladder
        if result is None:
            # Stage 4 — the hook: the one per-board call, data in, grade out.
            assert row is not None and material is not None
            outcome: CaseGradeOutcome = await self.grade_case(
                GradeRequest(
                    case_id=selected_case.case_id,
                    input=TextPayload(text=selected_case.input),
                    # A refusal or empty answer carries no output payload; its text
                    # rides on the assembled result, not through the hook.
                    answer=(
                        TextPayload(text=output)
                        if (output := _candidate_fields(row).output) is not None
                        else None
                    ),
                    row=row,
                    material=material,
                )
            )
            result = self._graded_result(
                selected_case, selected_index, row, outcome, extra_metadata
            )
        return result

    def _ladder_result(
        self,
        selected: SelectedCase,
        selected_index: int,
        indexed: RowIndex,
        row: Mapping[str, Any] | None,
        material: object | None,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult | _Omitted | None:
        """Stage 3 — the ladder, most-broken first; ``None`` means the Case is gradeable."""

        case_id = int(selected.case_id)
        result: CaseResult | _Omitted | None
        grading_failure: CaseExecutionOutcome | None = indexed.grading_failures.get(case_id)
        if grading_failure is not None:
            assert grading_failure.error is not None
            result = grading_failure_case_result(
                selected_case=selected,
                candidate=grading_failure.candidate,
                error=grading_failure.error,
                method=self.method,
                default_code=self.grading_failure_code,
                default_message=self.grading_failure_message,
            )
        elif self.error_row_result is not None and row is not None and "error" in row:
            # A board that owns its error rows also owns their rank: the broken row
            # is reported before the board's own missing material (draco's order).
            result = self.error_row_result(selected, selected_index, row)
        elif material is None:
            result = self._missing_material(selected, selected_index, row, extra_metadata)
        elif row is None:
            result = self._missing_row(selected, selected_index, indexed, case_id, extra_metadata)
        elif "error" in row:
            failure = self._failure(case_id, "candidate", "case_error", error=row["error"])
            result = self._failed_result(selected, row, [], failure, extra_metadata)
        else:
            result = None
        return result

    def _missing_material(
        self,
        selected: SelectedCase,
        selected_index: int,
        row: Mapping[str, Any] | None,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult:
        """The missing-material rung: board-owned shape when the hook is set."""

        if self.missing_material_result is not None:
            return self.missing_material_result(selected, selected_index, row)
        failure: dict[str, Any] = self._failure(
            int(selected.case_id), "grading", self.missing_material_code
        )
        return self._failed_result(selected, row, [], failure, extra_metadata)

    def _missing_row(
        self,
        selected: SelectedCase,
        selected_index: int,
        indexed: RowIndex,
        case_id: int,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult | _Omitted:
        """The missing-row rung: board-owned shape — or omission — when the hook is set."""

        orphans: list[dict[str, Any]] | None = indexed.collected_errors.get(case_id)
        if self.missing_row_result is None:
            return self._missing_row_result(selected, orphans, extra_metadata)
        board_result: CaseResult | None = self.missing_row_result(selected, selected_index, orphans)
        # None from the board hook means "file nothing" — the finalizer reports
        # the Case as case_result_missing (draco's pinned shape).
        return board_result if board_result is not None else _OMITTED

    def _graded_result(
        self,
        selected: SelectedCase,
        selected_index: int,
        row: Mapping[str, Any],
        outcome: CaseGradeOutcome,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult:
        if outcome.failure_code is not None:
            if self.hook_failure_result is not None:
                # The board owns the whole failed shape (draco keeps its zeroed
                # metric block and judge checks as audit material in the grade).
                return self.hook_failure_result(selected, selected_index, row, outcome)
            failure: dict[str, Any] = self._failure(
                int(selected.case_id),
                "grading",
                outcome.failure_code,
                judged=outcome.metrics.get("judged"),
                expected=outcome.metrics.get("expected"),
            )
            return self._failed_result(selected, row, outcome.checks, failure, extra_metadata)
        return self._scored_result(selected, row, outcome, extra_metadata)

    def _scored_result(
        self,
        selected: SelectedCase,
        row: Mapping[str, Any],
        outcome: CaseGradeOutcome,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult:
        assert outcome.score is not None
        fields: CandidateFields = _candidate_fields(row)
        grade: dict[str, Any] = {
            "method": self.method,
            "score": round(outcome.score, 4),
            "metrics": dict(outcome.metrics),
            "checks": list(outcome.checks),
        }
        common: dict[str, Any] = {
            "selected_case": selected,
            "finish_reason": fields.finish_reason,
            "grade": grade,
            "metadata": {**fields.metadata, **extra_metadata},
            "execution": fields.execution,
            "operations": fields.operations,
        }
        if fields.status == "refused":
            # WHY (OME-1037): the builder decides scored-vs-failed — a graded
            # refusal with text is scored; a textless provider decline is failed.
            return refusal_case_result(refusal=fields.refusal, **common)
        return scored_case_result(output=fields.output, **common)

    def _missing_row_result(
        self,
        selected: SelectedCase,
        orphan_errors: list[dict[str, Any]] | None,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult:
        # WHY the collected_errors attachment: an on_error=collect row loses its
        # Case identity, so a mid-chain error surfaces HERE as a missing row —
        # without the orphan payloads the report would name the symptom but hide
        # the cause (exactly what happened in the first live smoke run).
        failure: dict[str, Any] = self._failure(
            int(selected.case_id),
            "candidate",
            "missing_case_row",
            **({"collected_errors": orphan_errors[:3]} if orphan_errors else {}),
        )
        return self._failed_result(selected, None, [], failure, extra_metadata)

    def _failed_result(
        self,
        selected: SelectedCase,
        row: Mapping[str, Any] | None,
        checks: Sequence[Mapping[str, Any]],
        failure: dict[str, Any],
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult:
        fields: CandidateFields = _candidate_fields(row)
        # WHY a grade with score None rather than no grade: the judge evidence for a
        # partially judged Case is audit material, and the grade's checks list is the
        # contract's slot for it. Its metrics stay {} — a failed Case publishes no
        # counting claims (byte-identical to the pre-extraction boards).
        grade: dict[str, Any] = {
            "method": self.method,
            "score": None,
            "metrics": {},
            "checks": checks,
        }
        common: dict[str, Any] = {
            "selected_case": selected,
            "finish_reason": fields.finish_reason,
            "grade": grade,
            "failures": [failure],
            "metadata": {**fields.metadata, **extra_metadata},
            "execution": fields.execution,
            "operations": fields.operations,
        }
        if fields.status == "refused":
            return refusal_case_result(refusal=fields.refusal, **common)
        return failed_case_result(output=fields.output, **common)

    def _failure(self, case_id: int, stage: str, code: str, **metadata: Any) -> dict[str, Any]:
        public_metadata: dict[str, Any] = _failure_metadata(metadata)
        message: str = self.failure_messages[code]
        retryable: bool | None = None
        if source_error := _source_error(metadata):
            diagnostic: PublicError = public_error(
                source_error, default_code=code, default_message=message
            )
            message = diagnostic.message
            retryable = diagnostic.retryable
            public_metadata["source_error"] = {
                "kind": diagnostic.kind,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "retryable": diagnostic.retryable,
            }
        return {
            "stage": stage,
            "code": code,
            "message": message,
            "retryable": retryable,
            "case_id": case_id,
            "metadata": public_metadata,
        }


def _run_sync[T](coroutine: Awaitable[T]) -> T:
    """Drive the async hook chain to completion from the sync aggregate handler.

    WHY the thread branch: a url4 node runs its handlers inside an already-running
    event loop, where ``asyncio.run`` raises. Blocking that loop's thread is the
    pre-existing contract (the whole aggregate step is synchronous), so the hook
    chain runs to completion on a private loop in a worker thread there, and on a
    plain ``asyncio.run`` everywhere else.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_awaited(coroutine))
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _awaited(coroutine)).result()


async def _awaited[T](coroutine: Awaitable[T]) -> T:
    return await coroutine


@dataclass(frozen=True, slots=True)
class CandidateFields:
    """The Candidate's half of one row, already normalized — unusable values are ``None``.

    ``output``/``finish_reason``/``refusal`` are ``None`` unless the row carried a
    usable string (a blank refusal is unusable): "no usable answer" is a grading fact
    here, never a validation error. ``status``/``execution``/``operations`` pass
    through untouched — the result builders own their interpretation.
    """

    status: Any
    output: str | None
    finish_reason: str | None
    refusal: str | None
    execution: Any
    operations: Any
    metadata: dict[str, Any]


def _candidate_fields(row: Mapping[str, Any] | None) -> CandidateFields:
    """Pull status/output/finish_reason/refusal/metadata off the hoisted Case record."""

    case: object = row.get("case") if isinstance(row, Mapping) else None
    if not isinstance(case, Mapping):
        return CandidateFields(
            status=None,
            output=None,
            finish_reason=None,
            refusal=None,
            execution=None,
            operations=None,
            metadata={},
        )
    metadata: object = case.get("metadata")
    output: object = case.get("output")
    finish_reason: object = case.get("finish_reason")
    refusal: object = case.get("refusal")
    return CandidateFields(
        status=case.get("status"),
        output=output if isinstance(output, str) else None,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        refusal=refusal if isinstance(refusal, str) and refusal.strip() else None,
        execution=case.get("execution"),
        operations=case.get("operations"),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _failure_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {"judged", "expected", "row_index"}
        and isinstance(value, int)
        and not isinstance(value, bool)
    }


def _source_error(metadata: Mapping[str, Any]) -> Mapping[str, Any] | None:
    error: object = metadata.get("error")
    if isinstance(error, Mapping):
        return error
    collected: object = metadata.get("collected_errors")
    rows: list[Any] = collected[:3] if isinstance(collected, list) else []
    return next(
        (
            source
            for row in rows
            if isinstance(row, Mapping) and isinstance((source := row.get("error")), Mapping)
        ),
        None,
    )


__all__ = [
    "CaseGradeOutcome",
    "ErrorRowResult",
    "MissingMaterialResult",
    "GradeCase",
    "GradeRequest",
    "HookFailureResult",
    "MissingRowResult",
    "ScoredPath",
]
