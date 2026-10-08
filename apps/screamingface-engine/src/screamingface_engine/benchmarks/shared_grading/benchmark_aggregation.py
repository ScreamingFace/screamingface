"""The shared scored path — every rubric benchmark's marking room, written once.

A benchmark run is an url4 expression that fans out one sub-call per Case — 100 benchmark
questions → 100 parallel candidate calls. It returns one row per Case (the graded paper),
and this module is the marking room that turns the pile into the benchmark result.
The only per-benchmark step is ``grade_case`` — the one function every benchmark writes to
mark one script; everything around it (the roll call, the failure ladder, result
assembly, the benchmark-level reduction) is shared-grading machinery a benchmark author never sees.

The goal of this module is to have a shared grading pipeline (the "shared-grading"), and each
benchmark only plugs in its own marking logic. Before this shared module, ``gdpval/grade.py``
and ``healthbench/grade.py`` each had their own copy of the same ~code: the loop that files
rows by case, runs the failure ladder, grades each case, and computes the final score.
The copies were almost character-for-character the same.
This is the path for any rubric-scored (LLM-as-judge) benchmark, present or future.

One aggregate call = marking one class's benchmark.
- Stage 1 — roll call. Get the class list: which Cases (questions/students) were selected
    for this run, in order. Say Cases [3, 7, 12].
- Stage 2 — sort the pile. The fan-out dumped back a pile of result rows in whatever order.
    CaseGradeReader files each row under its Case id, so "give me Case 7's paper" is a lookup.
- Stage 3 — the ladder: decide if each paper is even gradeable. Before marking, check each
    Case against a list of broken states, worst first. First match wins, and the Case becomes
    a visible failure in the results — never silently dropped:
        - the grading step itself errored earlier → benchmark's own failure code
        - there's nothing to grade against (rubric asset missing) → missing_rubric_asset
        - no paper turned up for this student at all → missing_case_row; when the lost
          row left a named cause (the model ran out of tokens → model_token_cap), that
          cause is the code instead, with the source error kept in metadata
        - a paper turned up but it's an error report, not an answer → case_error
        - Example: Case 7's row is an error case → it gets a case_error result and skips Stage 4.
- Stage 4 — mark the survivors. For each Case that passed the ladder, call grade_case,
    the one function the benchmark author writes. Answer + rubric in, grade out.
    The hook can still fail a Case (e.g. the judge returned verdicts for only 3 of 5 rubric
    points → incomplete_verdicts), and the failure message text belongs to the benchmark,
    not the shared grading code.
- Stage 5 — total the marks. Wrap each Case's outcome into a `CaseResult`, then compute the
    benchmark-level score with the shared scorer. The benchmark contributes exactly one thing
    here: its mean (how per-Case scores average into the headline number). Everything else —
    the metric names in the output — is fixed shared-grading vocabulary, so every benchmark's
    report looks the same.

The key design point: Stages 1, 2, 3, 5 are identical for every benchmark (shared-grading).
Only Stage 4's grade_case (plus failure wording and the mean) is per-benchmark.

INVARIANT (the hourglass waist): a ``GradeRequest`` carries only plain, serializable
data — kind-tagged payloads, the decoded row mapping, the benchmark's grading material.
No ``Path``, no engine objects, no callbacks. Three consumers force this: an enclave
judge across a privacy boundary, the inspect_evals scorer adapter, and agentic benchmarks.

INVARIANT: failure codes and message texts stay byte-identical per benchmark — wording is
benchmark-supplied (gdpval says "criterion" where healthbench says "rubric item"); the
extraction moves logic, never words. The e2e goldens pin every failed Case's code.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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
from screamingface_engine.benchmarks.contract import CaseId, CaseResult
from screamingface_engine.benchmarks.graded_answer import GradedAnswer
from screamingface_engine.benchmarks.progress import completed_case, grading_progress
from screamingface_engine.benchmarks.shared_grading.case_grades import (
    CaseGradeIndex,
    CaseGradeReader,
)
from screamingface_engine.benchmarks.shared_grading.payloads import CasePayload, TextPayload


@dataclass(frozen=True, slots=True)
class GradeRequest:
    """Everything a benchmark needs to mark one script — plain data, nothing else.

    Attributes:
        case_id: the Case being graded.
        input: what the Candidate was asked, as a kind-tagged payload.
        answer: what it answered, or ``None`` when no usable answer text exists
            (a refusal's text rides on the assembled result, not here).
        row: the benchmark-decoded evaluation envelope — the judge's work is inside it.
        material: the benchmark's grading material for this Case (rubric points today;
            a label or verifier command for later grading modes). Opaque to the shared grading code.
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
    "no_positive_points"); the benchmark's message table supplies its wording. A graded
    Case carries ``score`` and ``failure_code=None`` — never both.
    """

    # WHY Any, not int (OME-1100): draco's per-Case metric block carries floats,
    # None (an unobserved axis), and nested per-axis dicts — counting claims are a
    # benchmark vocabulary, not a shared-grading one.
    score: float | None
    metrics: Mapping[str, Any]
    checks: Sequence[Mapping[str, Any]]
    failure_code: str | None = None
    # FEATURE (OME-1268): the Case's Named Scores, headline first; `score` IS the headline.
    # Empty for every single-scorer hook, so existing benchmarks construct this unchanged.
    scores: Mapping[str, float | None] = field(default_factory=dict)


#: The seam every benchmark implements: async because the call may be a network hop
#: (an enclave judge), data-only because nothing else crosses a privacy boundary.
type GradeCase = Callable[[GradeRequest], Awaitable[CaseGradeOutcome]]

#: A benchmark-owned replacement for the whole missing-case CaseResult — called as
#: ``(selected, selected_index, orphan_errors_or_None)``. WHY the whole result and
#: not just the failure dict: ifeval publishes a missing-case Case with ``grade: None``
#: (no grade envelope at all), and its golden pins that shape byte-for-byte.
#: Returning ``None`` (OME-1100) files NOTHING for the Case, so the finalizer
#: materialises it as ``case_result_missing`` — draco's pinned missing-case shape.
type MissingCaseResult = Callable[
    [SelectedCase, int, list[dict[str, Any]] | None], CaseResult | None
]

#: A benchmark-owned replacement for the whole error-case CaseResult — called as
#: ``(selected, selected_index, row)`` where ``row`` carries the ``"error"`` payload.
#: WHY (OME-1100): draco publishes the UPSTREAM error's own code ("rate_limited",
#: "provider_error") on a candidate-stage failure with no grade envelope, where the
#: shared-grading default publishes the fixed ``case_error`` code with an empty grade — the
#: e2e failure tapes pin draco's shape byte-for-byte.
type ErrorCaseResult = Callable[[SelectedCase, int, Mapping[str, Any]], CaseResult]

#: A benchmark-owned replacement for the whole missing-material CaseResult — called as
#: ``(selected, selected_index, row_or_None)`` when ``grading_material`` returned
#: ``None``. WHY (OME-1100): draco pins ``missing_case_rubric`` with a ``row_index``
#: and no grade envelope, with the Candidate's answer retained off the row.
type MissingMaterialResult = Callable[[SelectedCase, int, Mapping[str, Any] | None], CaseResult]

#: A benchmark-owned replacement for the whole hook-failure CaseResult — called as
#: ``(selected, selected_index, row, outcome)`` when the benchmark's ``grade_case``
#: returned a ``failure_code``. WHY (OME-1100): draco's incomplete Case keeps its
#: full zeroed metric block and its judge checks in the grade (audit material) with
#: a ``row_index`` failure, where the default assembly publishes empty metrics with
#: judged/expected counts.
type HookFailureResult = Callable[
    [SelectedCase, int, Mapping[str, Any], CaseGradeOutcome], CaseResult
]


class _Omitted:
    """Sentinel: the benchmark's missing-case hook filed nothing for this Case.

    Distinct from ``None`` on the ladder, which means "the Case is gradeable".
    """


_OMITTED = _Omitted()


@dataclass(frozen=True, slots=True)
class BenchmarkAggregation:
    """One benchmark's scored path — the shared stages bound to the benchmark's own seam.

    Each benchmark constructs one module-level instance. What a benchmark still owns:

    Attributes:
        reader: the benchmark's `CaseGradeReader` (its label, error class, envelope decoder).
        grade_case: the benchmark's hook — the only per-benchmark grading code.
        failure_messages: failure code → the public message shown for it. Wording is
            benchmark voice; this path never invents text.
        method: the grade's published method label ("rubric" for the rubric benchmarks,
            "deterministic" for ifeval).
        grading_failure_code: the benchmark's code for "the grading step itself failed".
        grading_failure_message: its default public message.
        missing_case_result: optional benchmark-owned builder for the WHOLE missing-case
            CaseResult (wording, codes, grade shape). ``None`` keeps the shared grading code
            default (the orphan's own code when it names one, e.g. ``model_token_cap``,
            else ``missing_case_row``; the orphan cause attached either way). WHY
            (OME-1101): ifeval's recorded golden pins its own collected-row wording
            (stage "grading", the diagnostic's code), and OME-981 owns the
            candidate-vs-grading boundary decision — the shared grading code must not default it.
        error_case_result: optional benchmark-owned builder for the WHOLE error-case
            CaseResult. A benchmark that sets it also owns the rung's RANK: its error
            rows are reported before the material rung (draco reports a broken row
            over its own missing rubric). ``None`` keeps the ``case_error`` default.
        missing_material_result: optional benchmark-owned builder for the WHOLE
            missing-material CaseResult. ``None`` keeps the ``missing_rubric_asset``
            default.
        hook_failure_result: optional benchmark-owned builder for the WHOLE CaseResult
            of a hook-reported failure (``grade_case`` returned a ``failure_code``).
            ``None`` keeps the default assembly (empty metrics, judged/expected
            metadata).
        missing_material_code: the published failure code when a Case's grading
            material is unusable (the default missing-material rung only — a
            ``missing_material_result`` hook owns its whole shape). WHY benchmark-named
            (OME-1149): the rubric benchmarks say ``missing_rubric_asset``, but an MCQ
            benchmark's material is its answer key — publishing a rubric-flavored code
            there would contradict its own message.
        inverted_grade: the Benchmark's Case scores are already 1 − its eval's grade
            (OME-1400). Stamped onto the run result so a replayed report can show it.
    """

    reader: CaseGradeReader
    grade_case: GradeCase
    failure_messages: Mapping[str, str]
    method: str
    grading_failure_code: str
    grading_failure_message: str
    missing_case_result: MissingCaseResult | None = None
    error_case_result: ErrorCaseResult | None = None
    missing_material_result: MissingMaterialResult | None = None
    hook_failure_result: HookFailureResult | None = None
    missing_material_code: str = "missing_rubric_asset"
    inverted_grade: bool = False
    # FEATURE (OME-1268): the row's declared Named Score keys, headline first. When set, a
    # scored Case's `scores` must carry exactly these keys and its headline column must
    # equal `score` — checked HERE because this is where the row is known (plan D4).
    named_scores: Sequence[str] = ()

    def aggregate(
        self,
        raw_case_grades: str,
        *,
        benchmark_id: str,
        benchmark_revision: str,
        selected_cases: Sequence[SelectedCase],
        grading_material: Callable[[int], object | None],
        scorer: Callable[[Sequence[CaseResult]], CandidateScore],
        case_metadata: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Mark every selected Case, then score the benchmark with the benchmark's own scorer.

        Args:
            raw_case_grades: the collected array of Case execution rows, in selected order.
            benchmark_id: the benchmark publishing this result.
            benchmark_revision: that benchmark's revision, stamped into the result.
            selected_cases: the authoritative roll call, in selected order.
            grading_material: per-Case loader for the benchmark's grading material;
                ``None`` marks the material unusable (``missing_material_code``).
            scorer: the benchmark-level reduction, the benchmark's whole ``CandidateScore``
                builder. Rubric benchmarks bind ``mean_scorer(mean)`` (fixed rubric
                vocabulary, mean the only choice); a non-rubric benchmark (ifeval)
                supplies its published metric vocabulary here (OME-1101).
            case_metadata: optional per-Case loader for PUBLIC report metadata that
                does not ride the row (OME-1149: MedXpertQA's slice tags live in the
                private answer asset). Merged into the shared grading code-assembled scored and
                failed results, so failure-mode analysis can group by the same axes;
                row-level grading failures and benchmark-owned result hooks keep their
                own (pre-fold) shape.

        Returns:
            The Candidate result payload: every selected Case, its grade or its
            failure, the benchmark score, and the run's factual coverage.
        """

        # WHY the sync face stays: every existing benchmark's aggregate handler is a
        # sync url4 endpoint; only the async face below changes who drives the loop.
        return _run_sync(
            self.aggregate_async(
                raw_case_grades,
                benchmark_id=benchmark_id,
                benchmark_revision=benchmark_revision,
                selected_cases=selected_cases,
                grading_material=grading_material,
                scorer=scorer,
                case_metadata=case_metadata,
            )
        )

    async def aggregate_async(
        self,
        raw_case_grades: str,
        *,
        benchmark_id: str,
        benchmark_revision: str,
        selected_cases: Sequence[SelectedCase],
        grading_material: Callable[[int], object | None],
        scorer: Callable[[Sequence[CaseResult]], CandidateScore],
        case_metadata: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """:meth:`aggregate`, awaited on the CALLER's loop — same args, same result.

        WHY it exists (OME-1240): a hook that makes model calls (a judged imported
        benchmark) must run on the loop that owns the run's HTTP client — httpx refuses
        a pooled connection created on another loop ("bound to a different event
        loop"), so the sync face's worker-thread loop cannot carry it. url4 awaits
        async endpoint handlers natively, so a judged aggregate registers an async
        handler over this face and no second loop ever exists.
        """

        with grading_progress(benchmark_id, benchmark_revision, scorer):
            case_results = []
            async for result in self.iter_case_results(
                raw_case_grades,
                selected_cases=selected_cases,
                grading_material=grading_material,
                case_metadata=case_metadata,
            ):
                case_results.append(result)
                # INVARIANT: publish only after canonical grading; observing never regrades.
                completed_case(benchmark_id, benchmark_revision, result, scorer)
            # Stage 5 — fold the marks into the class results.
            finalized = finalize_candidate_result(
                benchmark_id=benchmark_id,
                benchmark_revision=benchmark_revision,
                selected_cases=list(selected_cases),
                cases=case_results,
                scorer=scorer,
                inverted_grade=self.inverted_grade,
            )
            observed = {case.case_id for case in case_results}
            for case in finalized.cases:
                if case.case_id not in observed:
                    completed_case(benchmark_id, benchmark_revision, case, scorer)
            return finalized.as_payload()

    async def iter_case_results(
        self,
        raw_case_grades: str,
        *,
        selected_cases: Sequence[SelectedCase],
        grading_material: Callable[[int], object | None],
        case_metadata: Callable[[int], Mapping[str, Any]] | None = None,
    ) -> AsyncGenerator[CaseResult]:
        """Yield canonical grades in selected order, before grading the next case.

        Consuming this iterator executes grading; it is not an observer or replay.
        All collected rows are validated before the first grade. A caller that
        stops consuming must close the iterator; remaining cases are not graded.
        Missing-row hooks that omit a result remain omitted: final aggregation
        owns their conversion into case_result_missing failures.

        FEATURE: OME-932's incremental consumer shares final aggregation's exact
        grade path. This does not move grade production earlier in the URL4 graph.
        """
        case_ids = tuple(int(selected.case_id) for selected in selected_cases)
        indexed = self.reader.index(raw_case_grades, case_ids)
        for index, selected in enumerate(selected_cases):
            result = await self.case_result(
                selected, index, indexed, grading_material, case_metadata
            )
            if result is not None:
                yield result

    async def case_result(
        self,
        selected_case: SelectedCase,
        selected_index: int,
        indexed: CaseGradeIndex,
        grading_material: Callable[[int], object | None],
        case_metadata: Callable[[int], Mapping[str, Any]] | None,
    ) -> CaseResult | None:
        """Grade one selected Case with the same failure ladder as batch grading.

        The original selected index preserves anonymous failure attribution.
        ``None`` retains a board's explicit omission policy.
        """
        case_id: int = int(selected_case.case_id)
        row: dict[str, Any] | None = indexed.case_grades.get(case_id)
        material: object | None = grading_material(case_id)
        extra_metadata: Mapping[str, Any] = case_metadata(case_id) if case_metadata else {}
        ladder: CaseResult | _Omitted | None = self._ladder_result(
            selected_case, selected_index, indexed, row, material, extra_metadata
        )
        if isinstance(ladder, _Omitted):
            return None
        result: CaseResult | None = ladder
        if result is None:
            # Stage 4 — the hook: the one per-benchmark call, data in, grade out.
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
        indexed: CaseGradeIndex,
        row: Mapping[str, Any] | None,
        material: object | None,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult | _Omitted | None:
        """Stage 3 — the ladder, most-broken first; ``None`` means the Case is gradeable."""

        case_id = int(selected.case_id)
        result: CaseResult | _Omitted | None
        grading_failure: GradedAnswer | None = indexed.grading_failures.get(case_id)
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
        elif self.error_case_result is not None and row is not None and "error" in row:
            # A benchmark that owns its error cases also owns their rank: the broken row
            # is reported before the benchmark's own missing material (draco's order).
            result = self.error_case_result(selected, selected_index, row)
        elif material is None:
            result = self._missing_material(selected, selected_index, row, extra_metadata)
        elif row is None:
            result = self._missing_case(selected, selected_index, indexed, case_id, extra_metadata)
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
        """The missing-material rung: benchmark-owned shape when the hook is set."""

        if self.missing_material_result is not None:
            return self.missing_material_result(selected, selected_index, row)
        failure: dict[str, Any] = self._failure(
            int(selected.case_id), "grading", self.missing_material_code
        )
        return self._failed_result(selected, row, [], failure, extra_metadata)

    def _missing_case(
        self,
        selected: SelectedCase,
        selected_index: int,
        indexed: CaseGradeIndex,
        case_id: int,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult | _Omitted:
        """The missing-case rung: benchmark-owned shape — or omission — when the hook is set."""

        orphans: list[dict[str, Any]] | None = indexed.collected_errors.get(case_id)
        if self.missing_case_result is None:
            return self._missing_case_result(selected, orphans, extra_metadata)
        benchmark_result: CaseResult | None = self.missing_case_result(
            selected, selected_index, orphans
        )
        # None from the benchmark hook means "file nothing" — the finalizer reports
        # the Case as case_result_missing (draco's pinned shape).
        return benchmark_result if benchmark_result is not None else _OMITTED

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
                # The benchmark owns the whole failed shape (draco keeps its zeroed
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
        if self.named_scores:
            grade["scores"] = self._named_scores(outcome)
        elif outcome.scores:
            # WHY refuse, not publish: a column nobody declared would reach the wire under
            # no row's name; the Benchmark, not the hook, says which columns exist.
            raise ValueError(
                f"the grading hook returned Named Scores {list(outcome.scores)} but the "
                "Benchmark declares none"
            )
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

    def _named_scores(self, outcome: CaseGradeOutcome) -> dict[str, float | None]:
        """The Case's Named Scores as the grade publishes them: declared keys, headline first.

        INVARIANT: the key set equals the row's `named_scores` in order, and the headline
        column equals the Case score, so a column nobody declared can never be published
        and the headline on the wire never disagrees with `score`.
        """

        declared: tuple[str, ...] = tuple(self.named_scores)
        observed: tuple[str, ...] = tuple(outcome.scores)
        if observed != declared:
            raise ValueError(
                f"Case Grade scores {list(observed)} differ from the declared named_scores "
                f"{list(declared)}"
            )
        rounded: dict[str, float | None] = {
            name: None if value is None else round(value, 4)
            for name, value in outcome.scores.items()
        }
        if rounded[declared[0]] != round(outcome.score or 0.0, 4):
            raise ValueError(
                f"Case Grade headline column {declared[0]!r} ({rounded[declared[0]]}) differs "
                f"from the Case score ({round(outcome.score or 0.0, 4)})"
            )
        return rounded

    def _missing_case_result(
        self,
        selected: SelectedCase,
        orphan_errors: list[dict[str, Any]] | None,
        extra_metadata: Mapping[str, Any],
    ) -> CaseResult:
        # WHY the collected_errors attachment: an on_error=collect row loses its
        # Case identity, so a mid-chain error surfaces HERE as a missing case —
        # without the orphan payloads the report would name the symptom but hide
        # the cause (exactly what happened in the first live smoke run).
        failure: dict[str, Any] = self._failure(
            int(selected.case_id),
            "candidate",
            "missing_case_row",
            **({"collected_errors": orphan_errors[:3]} if orphan_errors else {}),
        )
        # WHY (OME-1390, owner decision): "missing" must not cover for a real cause.
        # A token-exhausted Case read as missing_case_row, so the report and the paid
        # smoke (which tolerates model_token_cap) blamed the engine. The source code
        # is already sanitized into the closed vocabulary by public_error, and a
        # source error with no code of its own defaults to missing_case_row — so an
        # orphan with no named cause still reads as missing.
        if (source_error := failure["metadata"].get("source_error")) is not None:
            failure["code"] = source_error["code"]
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
        # counting claims (byte-identical to the pre-extraction benchmarks).
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
            if diagnostic.source_code is not None:
                # The upstream spelling folded into upstream_error — kept for on-call.
                public_metadata["source_error"]["source_code"] = diagnostic.source_code
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
    # INVARIANT (OME-1240): the worker thread runs under a COPY of the caller's
    # context, so ContextVars bound around the aggregate — the url4 executor's
    # usage/response/log sinks — stay visible to the hook chain. A judge-calling
    # hook reports its tokens through that sink; a thread starting from an empty
    # context would silently drop the judge's cost from the run. The caller
    # blocks on `.result()`, so the bindings outlive the whole worker run.
    context = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(context.run, asyncio.run, _awaited(coroutine)).result()


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
    "ErrorCaseResult",
    "MissingMaterialResult",
    "GradeCase",
    "GradeRequest",
    "HookFailureResult",
    "MissingCaseResult",
    "BenchmarkAggregation",
]
