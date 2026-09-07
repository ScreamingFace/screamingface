"""The shared scored path — every rubric board's marking room, written once.

Think of a benchmark run as an exam: the fan-out returns one row per Case (the graded
paper), and this module is the marking room that turns the pile into the exam result.
The only per-board step is ``grade_case`` — the one function every benchmark writes to
mark one script; everything around it (the roll call, the failure ladder, result
assembly, the exam-level reduction) is spine machinery a board author never sees.

FEATURE: one grading spine per benchmark (OME-1024); this is the third extraction
(OME-1097) — it absorbs the near byte-identical ``aggregate`` orchestration and exam
scorer that ``gdpval`` and ``healthbench`` previously duplicated, and it dissolves
OME-1039's ``CaseGrader`` into the hook seam.

The stages, in execution order, for one ``ScoredPath.aggregate`` call:

    Stage 1  read the roll call        selected Cases, in selected order
    Stage 2  index the rows            `RowReader` files each row by Case id (OME-1096)
    Stage 3  per Case, run the ladder  unusable states become VISIBLE failures:
                 grading step failed        → the board's grading-failure code
                 no grading material        → "missing_rubric_asset"
                 no row for this Case       → "missing_case_row" (orphan cause attached)
                 row is an error row        → "case_error"
    Stage 4  per surviving Case, call `grade_case` — data in, grade out
                 the hook may itself fail the Case ("incomplete_verdicts",
                 "no_positive_points"); its wording still comes from the board
    Stage 5  assemble each CaseResult, then finalize with the shared exam scorer
             (the board's `mean` is the only parameter; the metric vocabulary is fixed)

Why so strict? A lenient reducer would quietly CHEAT in the submitter's favor: dropping
a failed Case inflates the mean (the failed ones are usually the hard ones), and
defaulting a missing verdict erases a rubric penalty. Every unusable state therefore
stays a visible failed Case with a named code.

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
    SelectedCase,
    failed_case_result,
    finalize_candidate_result,
    grading_failure_case_result,
    public_error,
    refusal_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseId, CaseResult
from screamingface_engine.benchmarks.spine.exam import exam_scorer
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

    score: float | None
    metrics: Mapping[str, int]
    checks: Sequence[Mapping[str, Any]]
    failure_code: str | None = None


#: The seam every benchmark implements: async because the call may be a network hop
#: (an enclave judge), data-only because nothing else crosses a privacy boundary.
type GradeCase = Callable[[GradeRequest], Awaitable[CaseGradeOutcome]]


@dataclass(frozen=True, slots=True)
class ScoredPath:
    """One board's scored path — the shared stages bound to the board's own seam.

    Each board constructs one module-level instance. What a board still owns:

    Attributes:
        reader: the board's `RowReader` (its label, error class, envelope decoder).
        grade_case: the board's hook — the only per-board grading code.
        failure_messages: failure code → the public message shown for it. Wording is
            board voice; this path never invents text.
        method: the grade's published method label ("rubric" for both current boards).
        grading_failure_code: the board's code for "the grading step itself failed".
        grading_failure_message: its default public message.
    """

    reader: RowReader
    grade_case: GradeCase
    failure_messages: Mapping[str, str]
    method: str
    grading_failure_code: str
    grading_failure_message: str

    def aggregate(
        self,
        raw_rows: str,
        *,
        benchmark_id: str,
        benchmark_revision: str,
        selected_cases: Sequence[SelectedCase],
        grading_material: Callable[[int], object | None],
        mean: Callable[[Sequence[float]], float | None],
    ) -> dict[str, Any]:
        """Mark every selected Case, then score the exam with the board's own mean.

        Args:
            raw_rows: the collected array of Case execution rows, in selected order.
            benchmark_id: the board publishing this result.
            benchmark_revision: that board's revision, stamped into the result.
            selected_cases: the authoritative roll call, in selected order.
            grading_material: per-Case loader for the board's grading material;
                ``None`` marks the material unusable ("missing_rubric_asset").
            mean: the exam-level reduction. INVARIANT: this is the ONLY place two
                boards of one family differ in scoring — everything per-Case is the
                hook's job, everything exam-level except the mean is fixed vocabulary.

        Returns:
            The Candidate result payload: every selected Case, its grade or its
            failure, the exam score, and the run's factual coverage.
        """

        # Stage 1-2 — roll call and row filing (position is identity; see rows.py).
        case_ids = tuple(int(selected.case_id) for selected in selected_cases)
        indexed = self.reader.index(raw_rows, case_ids)
        # Stage 3-4 — the hook is async (an enclave call is a network hop); the
        # surrounding url4 handler is sync.
        case_results = _run_sync(self._case_results(selected_cases, indexed, grading_material))
        # Stage 5 — fold the marks into the class results.
        return finalize_candidate_result(
            benchmark_id=benchmark_id,
            benchmark_revision=benchmark_revision,
            selected_cases=list(selected_cases),
            cases=case_results,
            scorer=exam_scorer(mean),
        ).as_payload()

    async def _case_results(
        self,
        selected_cases: Sequence[SelectedCase],
        indexed: RowIndex,
        grading_material: Callable[[int], object | None],
    ) -> list[CaseResult]:
        # WHY sequential, not gather: selected order is publication order, and no
        # current hook overlaps I/O; concurrency semantics are a later, separate call.
        return [
            await self._case_result(selected, indexed, grading_material)
            for selected in selected_cases
        ]

    async def _case_result(
        self,
        selected: SelectedCase,
        indexed: RowIndex,
        grading_material: Callable[[int], object | None],
    ) -> CaseResult:
        case_id = int(selected.case_id)
        row = indexed.rows.get(case_id)
        material = grading_material(case_id)
        result = self._ladder_result(selected, indexed, row, material)
        if result is None:
            # Stage 4 — the hook: the one per-board call, data in, grade out.
            assert row is not None and material is not None
            outcome = await self.grade_case(
                GradeRequest(
                    case_id=selected.case_id,
                    input=TextPayload(text=selected.input),
                    # A refusal or empty answer carries no output payload; its text
                    # rides on the assembled result, not through the hook.
                    answer=(
                        TextPayload(text=output)
                        if isinstance((output := _candidate_fields(row)["output"]), str)
                        else None
                    ),
                    row=row,
                    material=material,
                )
            )
            result = self._graded_result(selected, row, outcome)
        return result

    def _ladder_result(
        self,
        selected: SelectedCase,
        indexed: RowIndex,
        row: Mapping[str, Any] | None,
        material: object | None,
    ) -> CaseResult | None:
        """Stage 3 — the ladder, most-broken first; ``None`` means the Case is gradeable."""

        case_id = int(selected.case_id)
        result: CaseResult | None
        grading_failure = indexed.grading_failures.get(case_id)
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
        elif material is None:
            failure = self._failure(case_id, "grading", "missing_rubric_asset")
            result = self._failed_result(selected, row, [], failure)
        elif row is None:
            result = self._missing_row_result(selected, indexed.collected_errors.get(case_id))
        elif "error" in row:
            failure = self._failure(case_id, "candidate", "case_error", error=row["error"])
            result = self._failed_result(selected, row, [], failure)
        else:
            result = None
        return result

    def _graded_result(
        self,
        selected: SelectedCase,
        row: Mapping[str, Any],
        outcome: CaseGradeOutcome,
    ) -> CaseResult:
        if outcome.failure_code is not None:
            failure = self._failure(
                int(selected.case_id),
                "grading",
                outcome.failure_code,
                judged=outcome.metrics.get("judged"),
                expected=outcome.metrics.get("expected"),
            )
            return self._failed_result(selected, row, outcome.checks, failure)
        return self._scored_result(selected, row, outcome)

    def _scored_result(
        self,
        selected: SelectedCase,
        row: Mapping[str, Any],
        outcome: CaseGradeOutcome,
    ) -> CaseResult:
        assert outcome.score is not None
        fields = _candidate_fields(row)
        grade = {
            "method": self.method,
            "score": round(outcome.score, 4),
            "metrics": dict(outcome.metrics),
            "checks": list(outcome.checks),
        }
        common = {
            "selected_case": selected,
            "finish_reason": fields["finish_reason"],
            "grade": grade,
            "metadata": fields["metadata"],
            "execution": fields["execution"],
            "operations": fields.get("operations"),
        }
        if fields["status"] == "refused":
            # WHY (OME-1037): the builder decides scored-vs-failed — a graded
            # refusal with text is scored; a textless provider decline is failed.
            return refusal_case_result(refusal=fields["refusal"], **common)
        return scored_case_result(output=fields["output"], **common)

    def _missing_row_result(
        self,
        selected: SelectedCase,
        orphan_errors: list[dict[str, Any]] | None,
    ) -> CaseResult:
        # WHY the collected_errors attachment: an on_error=collect row loses its
        # Case identity, so a mid-chain error surfaces HERE as a missing row —
        # without the orphan payloads the report would name the symptom but hide
        # the cause (exactly what happened in the first live smoke run).
        failure = self._failure(
            int(selected.case_id),
            "candidate",
            "missing_case_row",
            **({"collected_errors": orphan_errors[:3]} if orphan_errors else {}),
        )
        return self._failed_result(selected, None, [], failure)

    def _failed_result(
        self,
        selected: SelectedCase,
        row: Mapping[str, Any] | None,
        checks: Sequence[Mapping[str, Any]],
        failure: dict[str, Any],
    ) -> CaseResult:
        fields = _candidate_fields(row)
        # WHY a grade with score None rather than no grade: the judge evidence for a
        # partially judged Case is audit material, and the grade's checks list is the
        # contract's slot for it. Its metrics stay {} — a failed Case publishes no
        # counting claims (byte-identical to the pre-extraction boards).
        grade = {"method": self.method, "score": None, "metrics": {}, "checks": checks}
        common = {
            "selected_case": selected,
            "finish_reason": fields["finish_reason"],
            "grade": grade,
            "failures": [failure],
            "metadata": fields["metadata"],
            "execution": fields["execution"],
            "operations": fields.get("operations"),
        }
        if fields["status"] == "refused":
            return refusal_case_result(refusal=fields["refusal"], **common)
        return failed_case_result(output=fields["output"], **common)

    def _failure(self, case_id: int, stage: str, code: str, **metadata: Any) -> dict[str, Any]:
        public_metadata = _failure_metadata(metadata)
        message = self.failure_messages[code]
        retryable: bool | None = None
        if source_error := _source_error(metadata):
            diagnostic = public_error(source_error, default_code=code, default_message=message)
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


def _candidate_fields(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Pull status/output/finish_reason/refusal/metadata off the hoisted Case record."""

    case = row.get("case") if isinstance(row, Mapping) else None
    if not isinstance(case, Mapping):
        return {
            "status": None,
            "output": None,
            "finish_reason": None,
            "refusal": None,
            "execution": None,
            "operations": None,
            "metadata": {},
        }
    metadata = case.get("metadata")
    output = case.get("output")
    finish_reason = case.get("finish_reason")
    refusal = case.get("refusal")
    return {
        "status": case.get("status"),
        "output": output if isinstance(output, str) else None,
        "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
        "refusal": refusal if isinstance(refusal, str) and refusal.strip() else None,
        "execution": case.get("execution"),
        "operations": case.get("operations"),
        "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
    }


def _failure_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {"judged", "expected", "row_index"}
        and isinstance(value, int)
        and not isinstance(value, bool)
    }


def _source_error(metadata: Mapping[str, Any]) -> Mapping[str, Any] | None:
    error = metadata.get("error")
    if isinstance(error, Mapping):
        return error
    collected = metadata.get("collected_errors")
    rows = collected[:3] if isinstance(collected, list) else []
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
    "GradeCase",
    "GradeRequest",
    "ScoredPath",
]
