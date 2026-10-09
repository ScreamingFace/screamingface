"""One factory turns an imported single-shot eval into a complete Engine benchmark.

Think of it as the plugin's own assembly line: hand it a benchmark's identity, its pinned
dataset facts, and its scorer, and it stamps out everything the engine expects — the
url4 protocol, the runtime routes, the BenchmarkAggregation binding, and the registration. The
per-benchmark modules (`gsm8k.py`, `mmlu.py`) shrink to declarations — the spec §5 "≤150
lines per benchmark" budget made structural.

The load-bearing move (spec §4): when a benchmark declares a draft-feedback offer, the SAME
wrapped scorer serves both the grading route (after the benchmark) and the mid-run check
(during it). MCQ benchmarks get NO draft-feedback offer — pass/fail feedback over a handful of
options is an elimination attack (OME-796), and the client preflight's refusal of a
loop recipe there is correct behavior.

FEATURE: imported inspect_evals benchmarks run in our product like any benchmark
(OME-1115, parent OME-1111).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Unpack

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_RESULT_SCHEMA,
    CaseGrade,
    CaseResult,
)
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkOrigin,
    DifficultyTier,
    DraftFeedbackOffer,
    candidate,
)
from screamingface_engine.benchmarks.deployment import (
    BenchmarkAssetBundle,
    BenchmarkAssetPreparer,
    BenchmarkRegistration,
)
from screamingface_engine.benchmarks.ensemble.policy import DRAFT_FEEDBACK_SCHEMA
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error as _contract_error,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    async_aggregate_endpoint,
    attempt_records_endpoint,
    candidate_answer,
    compact_json,
    json_object,
    positive_case_id,
)
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.provenance import ProvenanceFields
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.case_grades import (
    CaseGradeReader,
    read_selected_cases,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload
from screamingface_engine_inspect.envelopes import (
    CHECK_SCHEMA,
    build_case_grade,
    decode_case_grade,
)
from screamingface_engine_inspect.prepare import SKIPPED_MARKER
from screamingface_engine_inspect.revision_inputs import (
    PREPARER_REVISION,
    PROTOCOL_REVISION,
    pinned_inspect_packages,
)
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Request, Url4Node

# INVARIANT: imported grading is retrieval-free — their scorers compare text to a
# pinned answer key; a model that searched would answer a different question.
_CANDIDATE_WEB_SEARCH = False

# INVARIANT: failure wording is this plugin's published voice; no rubric-flavored
# codes may leak into an imported benchmark's result.
_FAILURE_MESSAGES: Mapping[str, str] = {
    "scorer_error": "the inspect scorer raised while grading this Case",
    "invalid_score_value": "the inspect scorer returned a value this board cannot map to a score",
    "missing_target_asset": "the baked target record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}

# WHY this text and nothing richer: mid-run feedback crosses into the candidate's
# context, so it must never carry the answer key or the scorer's explanation (which may
# quote it). Wrong-ness is the entire message; the sealed envelope holds.
_CHECK_FEEDBACK = (
    "The committed answer does not match the expected solution. "
    "Re-derive the result step by step and commit a corrected final answer."
)


class AggregateError(ValueError):
    """An imported benchmark's reducer input is unusable — raised before any scoring."""


@dataclass(frozen=True, slots=True)
class JudgeSpec:
    """A judged benchmark's declaration: its scorer calls a gateway judge.

    The declaration is half of a two-sided contract the assembly cross-checks, and
    the scorer reaches the judge one of two ways:

    - **by name** (``model_role`` is None): ``model`` must reappear as
      ``screamingface/<model>`` among the scorer's own kwargs (the string the
      scorer actually calls), so the pinned judge and the called judge can never
      drift apart.
    - **by role** (``model_role="grader"``): the scorer names no model and asks inspect
      for its grader role; the judged aggregate binds that role to
      ``screamingface/<model>`` for the grading pass, and the scorer kwargs must
      call no judge of their own (OME-1370).

    Attributes:
        model: the gateway model id the judge call goes to (the node route is
            ``/<model>``) — benchmark identity, hashed into the benchmark revision.
        params: protocol params pinned onto every judge call (e.g.
            ``(("temperature", "0"),)``) — benchmark identity too.
        model_role: the inspect model role this judge fills, or None when the scorer
            names its judge in a kwarg. Benchmark identity when set.
    """

    model: str
    params: tuple[tuple[str, str], ...] = ()
    model_role: str | None = None


@dataclass(frozen=True, slots=True)
class ImportedBenchmark:
    """One assembled imported benchmark — the benchmark plus its plugin-side bindings."""

    benchmark: Benchmark
    registration: BenchmarkRegistration
    scorer_factory: Callable[[], Any]
    multiple_correct: bool
    cases_route: str
    check_route: str
    check_surface_route: str
    case_evaluation_route: str
    aggregate_route: str
    #: The benchmark's judge declaration; None for every string-match benchmark (OME-1240).
    judge: JudgeSpec | None = None
    #: The eval's grade counts the unwanted behaviour; the scorer adapter scores 1 − grade
    #: (OME-1400). Already hashed into the revision by the caller's pins.
    inverted_grade: bool = False
    #: The judge's verdict word → grade map, replacing inspect's letters (OME-1371);
    #: None for every letter- or number-graded benchmark. Hashed by the caller's pins.
    verdict_grades: Mapping[str, float] | None = None
    #: The Task's other scorers (OME-1268), each a lazy factory like ``scorer_factory``;
    #: empty for every single-scorer benchmark. Hashed by the caller's pins.
    extra_scorer_factories: tuple[Callable[[], Any], ...] = ()
    #: The keys of the Case's Named Scores, headline first (OME-1268); empty for every
    #: single-scorer benchmark. Hashed by the caller's pins.
    named_scores: tuple[str, ...] = ()
    #: The eval's own whole-run metric as a lazy factory (OME-1527, R1); None tallies the
    #: mean of the Case scores, as every published Benchmark does. Hashed by the caller's pins.
    whole_run_metric_factory: Callable[[], Any] | None = None

    def aggregation(
        self, kept_scores: MutableMapping[int, Any] | None = None
    ) -> BenchmarkAggregation:
        """This benchmark's shared-grading binding — built on demand so the scorer stays lazy.

        ``kept_scores`` is one run's private store of the graded Cases' inspect Scores, for
        the tally of a row that honours the eval's whole-run metric; None keeps nothing.
        """

        # WHY lazy: the scorer adapter imports inspect_ai (which drags in a web stack and the
        # OTel SDK). Benchmark REGISTRATION happens at engine import in every mode; the
        # adapter is needed only when a Runner world actually grades, so the run entry
        # point's cold-start import budget stays untouched (test_cli /
        # test_span_export_wiring pin this).
        from screamingface_engine_inspect.scorer_adapter import inspect_grade_case

        return BenchmarkAggregation(
            reader=CaseGradeReader(
                benchmark_label=self.benchmark.title,
                error_type=AggregateError,
                decode_case_grade=_decode,
            ),
            grade_case=inspect_grade_case(
                self.scorer_factory(),
                extra_scorers=[factory() for factory in self.extra_scorer_factories],
                named_scores=self.named_scores,
                multiple_correct=self.multiple_correct,
                inverted_grade=self.inverted_grade,
                verdict_grades=self.verdict_grades,
                kept_scores=kept_scores,
            ),
            failure_messages=_FAILURE_MESSAGES,
            method="inspect_scorer",
            grading_failure_code="inspect_grading_failed",
            grading_failure_message="the inspect scorer pipeline could not grade this Case",
            missing_material_code="missing_target_asset",
            inverted_grade=self.inverted_grade,
            named_scores=self.named_scores,
        )


def imported_benchmark_id(benchmark_key: str, origin: BenchmarkOrigin) -> str:
    """The catalogue id this plugin gives a row: ``inspect-<key>`` for an inspect_evals import,
    the bare key for a local Task (our own eval in inspect's shape, OME-1513) — "musique", not
    "inspect-musique", because nothing about it came from inspect_evals."""

    return benchmark_key if origin == "screamingface" else f"inspect-{benchmark_key}"


def single_shot_benchmark(
    *,
    benchmark_key: str,
    title: str,
    description: str,
    focus: str,
    dataset_url: str,
    case_count: int,
    revision_pins: Sequence[str],
    scorer_factory: Callable[[], Any],
    prepare: BenchmarkAssetPreparer,
    install: Callable[[Url4Node, Path], None],
    with_check_surface: bool,
    difficulty: DifficultyTier,
    multiple_correct: bool = False,
    judge: JudgeSpec | None = None,
    inverted_grade: bool = False,
    verdict_grades: Mapping[str, float] | None = None,
    extra_scorer_factories: Sequence[Callable[[], Any]] = (),
    named_scores: Sequence[str] = (),
    origin: BenchmarkOrigin = "inspect_evals",
    whole_run_metric_factory: Callable[[], Any] | None = None,
    **provenance: Unpack[ProvenanceFields],
) -> ImportedBenchmark:
    """Assemble one imported single-shot benchmark from its declarations.

    Stage 1 — identity: benchmark id ``inspect-<key>`` (flat, OME-836) and the §6
              revision — sha over the pinned inspect packages + the dataset pins +
              the protocol constants, 16 hex chars.
    Stage 2 — protocol: the canonical one-invocation expression (ifeval's shape) —
              candidate answers ``$item.input``, the check route records the attempt,
              the aggregate grades everything engine-side through the scorer adapter.
    Stage 3 — runtime: an installer registering cases/check/case-evaluation/aggregate,
              plus the check-surface port iff declared.
    Stage 4 — registration: benchmark + asset bundle, ready for the entry point.

    Args:
        benchmark_key: the flat identity tail ("gsm8k" → benchmark id "inspect-gsm8k").
        title, description, focus, dataset_url: leaderboard display fields (OME-904).
        difficulty: the catalogue's hand-assigned easy→hard tier, authored on the
            BenchmarkSpec row (OME-1257).
        case_count: rows in the pinned split — the benchmark's declared benchmark size.
        revision_pins: every dataset fact that participates in benchmark identity.
        scorer_factory: zero-arg callable returning the imported eval's scorer.
        prepare: the benchmark's build-time asset preparer (its prepared copy of the dataset).
        install: the benchmark module's OWN installer wrapper (defined beside its
            ``ASSET_BUNDLE_ID`` constant, per the deployment conformance rule), which
            delegates to :func:`install_imported_benchmark`.
        with_check_surface: §4 dual registration; False for MCQ benchmarks (OME-796).
        multiple_correct: inspect's MCQ multi-answer flag, passed to the scorer adapter.
        judge: the benchmark's judge declaration (OME-1240) — the aggregate binds the
            judge transport from it, and its model + params are hashed into the
            revision below. None for every string-match benchmark.
        inverted_grade: the eval's grade counts the unwanted behaviour (a should-refuse
            safety benchmark); passed to the scorer adapter, which scores 1 − grade. The
            caller carries it into ``revision_pins`` (OME-1400).
        verdict_grades: the judge's verdict word → grade map for a judge that answers
            in words (coconot); passed to the scorer adapter, which then grades by it
            instead of inspect's letters. The caller carries it into ``revision_pins``
            (OME-1371).
        extra_scorer_factories: the Task's other scorers as lazy factories, in upstream
            order; the adapter grades each Case once per scorer (OME-1268). The caller
            carries them into ``revision_pins``.
        named_scores: the keys of the Case's Named Scores, headline first (OME-1268);
            empty on a single-scorer benchmark. The caller carries it into ``revision_pins``.
        whole_run_metric_factory: zero-arg callable returning the eval's own inspect metric,
            which then scores the whole run in place of the mean (OME-1527, R1); None keeps
            the mean. The caller carries its reference into ``revision_pins``.

    Returns:
        The assembled benchmark, its registration ready for the plugin's entry point.
    """

    benchmark_id: str = imported_benchmark_id(benchmark_key, origin)
    if judge is not None and with_check_surface:
        # WHY: a judged mid-run check spends judge tokens per attempt, and the
        # advertised check cost is still hardcoded "free" — until the check-cost
        # knob exists (OME-1116), a judged benchmark must not advertise a draft-feedback offer.
        raise ValueError(
            f"{benchmark_id}: a judged benchmark cannot declare a check surface until "
            "the check-cost knob lands (OME-1116)"
        )
    # WHY: pins are newline-joined below; a pin containing "\n" would make two
    # different pin lists hash identically — refused, never coerced.
    if any("\n" in pin for pin in revision_pins):
        raise ValueError(f"{benchmark_id}: revision_pins must not contain newlines")
    revision: str = hashlib.sha256(
        "\n".join(
            (
                *pinned_inspect_packages(),
                *revision_pins,
                PREPARER_REVISION,
                PROTOCOL_REVISION,
                EVALUATION_PROTOCOL_REVISION,
                CANDIDATE_RESULT_SCHEMA,
                # WHY hashed HERE, not left to revision_pins: the factory owns
                # identity math (§6 — the case subset rides the revision); a benchmark
                # author forgetting a pin must not get a subset change with an
                # unchanged benchmark identity.
                f"case_count={case_count}",
                f"check_surface={with_check_surface}",
                # WHY conditional pins (OME-1240): the judge is benchmark identity —
                # swapping the judge model or its pinned params is a different
                # benchmark — but an UNDECLARED benchmark contributes nothing here, so the
                # published string-match benchmarks' revisions stay byte-identical.
                *(
                    ()
                    if judge is None
                    else (
                        f"judge_model={judge.model}",
                        f"judge_params={json.dumps(list(judge.params))}",
                        # WHY conditional again: a named judge's pins must stay
                        # byte-identical, so FrontierScience's revision holds (OME-1370).
                        *(() if judge.model_role is None else (f"judge_role={judge.model_role}",)),
                    )
                ),
            )
        ).encode()
    ).hexdigest()[:16]
    prefix: str = f"/benchmarks/{benchmark_id}/{revision}"
    routes: dict[str, str] = {
        "cases": f"{prefix}/cases",
        "check": f"{prefix}/check",
        "check_surface": f"{prefix}/check-surface",
        "case_evaluation": f"{prefix}/case-evaluation",
        "aggregate": f"{prefix}/aggregate",
    }

    benchmark = Benchmark(
        id=benchmark_id,
        title=title,
        description=description,
        revision=revision,
        case_count=case_count,
        # WHY explicit: `Benchmark.origin` defaults to "screamingface", which is wrong for
        # every eval that arrives through here from inspect_evals — the listing groups by this
        # field (OME-1114), so a defaulted row would hide the imported shelf inside our own
        # group. A LOCAL Task (our own eval in inspect's shape, OME-1513) is the one caller
        # that passes "screamingface": it is ours, and the provenance rule then asks it for no
        # inspect porter list.
        origin=origin,
        # FEATURE: the researcher-visible refusal-rate mark (OME-1400) — the same flag the
        # scorer adapter flips on, published so report.json can show it.
        inverted_grade=inverted_grade,
        build=_build(routes, case_count),
        install=install,
        focus=focus,
        dataset_url=dataset_url,
        # Benchmark Provenance, baselines, notebook (OME-1455): authored on the BenchmarkSpec
        # row like `difficulty`, threaded through verbatim; shapes checked by `Benchmark`.
        **provenance,
        declaration=BenchmarkDeclaration(
            # WHY "coverage_declare": imported benchmarks reduce through the shared
            # finalize_candidate_result, which scores the gradeable subset and
            # publishes coverage — the declaration matches the code (OME-1039).
            failure_policy="coverage_declare",
            interaction="single_shot",
            # The tier is authored on the BenchmarkSpec row (the imported benchmark's one
            # authoring site) and threaded through verbatim (OME-1257).
            difficulty=difficulty,
        ),
        check_surface=(
            DraftFeedbackOffer(
                check_route=routes["check_surface"],
                feedback_intent="feedback",
                # Free: both proof benchmarks grade deterministically. No cost knob exists
                # yet (YAGNI) — OME-1116 adds one when the first model-graded
                # import lands.
                expected_check_cost="free",
            )
            if with_check_surface
            else None
        ),
    )
    imported = ImportedBenchmark(
        benchmark=benchmark,
        registration=BenchmarkRegistration(
            benchmark=benchmark,
            asset_bundle=BenchmarkAssetBundle(id=benchmark_id, prepare=prepare),
        ),
        scorer_factory=scorer_factory,
        multiple_correct=multiple_correct,
        cases_route=routes["cases"],
        check_route=routes["check"],
        check_surface_route=routes["check_surface"],
        case_evaluation_route=routes["case_evaluation"],
        aggregate_route=routes["aggregate"],
        judge=judge,
        inverted_grade=inverted_grade,
        verdict_grades=verdict_grades,
        extra_scorer_factories=tuple(extra_scorer_factories),
        named_scores=tuple(named_scores),
        whole_run_metric_factory=whole_run_metric_factory,
    )
    # WHY revision-compared, not presence-compared: re-assembling the identical
    # benchmark is harmless (tests do it), but a copy-pasted benchmark module that kept
    # the donor's key would resolve the WRONG benchmark's routes at install time —
    # its differing pins give it a different revision, so it is refused here.
    existing: ImportedBenchmark | None = _BENCHMARKS_BY_ID.get(benchmark_id)
    if existing is not None and existing.benchmark.revision != revision:
        raise ValueError(
            f"benchmark id {benchmark_id!r} is already assembled with a different "
            f"revision — duplicate benchmark_key?"
        )
    _BENCHMARKS_BY_ID[benchmark_id] = imported
    return imported


#: Benchmark-module installers resolve their benchmark here at install time —
#: `Benchmark.install` is a plain callable created BEFORE the ImportedBenchmark exists,
#: so it looks its benchmark up by id instead of capturing a forward reference.
_BENCHMARKS_BY_ID: dict[str, ImportedBenchmark] = {}


def install_imported_benchmark(node: Url4Node, assets: Path, benchmark_id: str) -> None:
    """Register one imported benchmark's routes — called by the benchmark module's installer.

    WHY the indirection: the deployment conformance rule wants each benchmark's installer
    defined in the module that exports its ``ASSET_BUNDLE_ID``; this function is the
    shared kitchen those thin wrappers delegate to.
    """

    benchmark: ImportedBenchmark = _BENCHMARKS_BY_ID[benchmark_id]
    root: Path = assets / benchmark_id
    routes: dict[str, str] = {
        "cases": benchmark.cases_route,
        "check": benchmark.check_route,
        "check_surface": benchmark.check_surface_route,
        "case_evaluation": benchmark.case_evaluation_route,
        "aggregate": benchmark.aggregate_route,
    }
    install_cases(node, routes["cases"], _cases(root))
    installed = frozenset(node.processor_routes())
    endpoints: list[tuple[str, Callable[[Request], str | Awaitable[str]]]] = [
        (routes["check"], _check(root)),
        (
            routes["case_evaluation"],
            attempt_records_endpoint(
                label=f"{benchmark.benchmark.title} Case evaluation",
                item_name="Attempt",
                bind=build_case_grade,
                observe_grading=False,
            ),
        ),
        (
            routes["aggregate"],
            # WHY: both scorer families stay on the owning loop for logs and model I/O.
            async_aggregate_endpoint(
                label=benchmark.benchmark.title,
                available_case_count=benchmark.benchmark.case_count,
                aggregate=_judged_aggregate(benchmark, root, node),
            )
            if benchmark.judge is not None
            else async_aggregate_endpoint(
                label=benchmark.benchmark.title,
                available_case_count=benchmark.benchmark.case_count,
                aggregate=_aggregate(benchmark, root),
            ),
        ),
    ]
    if benchmark.benchmark.check_surface is not None:
        # Spec §4 — the SAME scorer, second office hour: the advertised
        # check-surface port for the corrective loop.
        endpoints.append((routes["check_surface"], _check_surface(benchmark, root)))
    for route, handler in endpoints:
        if route not in installed:
            node.endpoint(route)(handler)


def _build(routes: Mapping[str, str], available: int) -> Callable[[int], Node]:
    """The canonical one-invocation expression — one answer per Case, graded once."""

    def build(case_count: int) -> Node:
        candidate_invocation = candidate(
            "$item.input",
            web_search=_CANDIDATE_WEB_SEARCH,
            case_id="$item.id",
            case_index="$index",
            case_count=str(case_count),
        )
        checked = expr(
            src(
                RelExpr(
                    path=routes["check"],
                    context="$candidate_invocation",
                    intent=Text("$item.case_id"),
                ),
                name="record",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=routes["case_evaluation"],
                    context=render(struct({"attempt_1": "$record"})),
                    intent=Text("$item.case_id"),
                ),
                name="case_evaluation",
                weight=0.0,
            ),
            intent=Text("$case_evaluation"),
        )
        return build_evaluation_protocol(
            cases_route=routes["cases"],
            case_evaluation=preserve_candidate_outcome(
                candidate_invocation=candidate_invocation,
                grading=checked,
                case_id="$item.id",
            ),
            selected_case_count=case_count,
            available_case_count=available,
            aggregate_route=routes["aggregate"],
        )

    return build


def _cases(root: Path) -> Callable[[], str]:
    @observe_phase(ActivityKind.CASE_LOADING)
    def cases() -> str:
        try:
            return (root / "cases.json").read_text(encoding="utf-8")
        except OSError as exc:
            # A gated benchmark skipped at image build (PR builds without the Hugging Face
            # token) leaves a marker saying so — name that instead of a bare IO error.
            skipped: Path = root / SKIPPED_MARKER
            if skipped.is_file():
                raise _unavailable(
                    "this image was built without this board's questions: "
                    + skipped.read_text(encoding="utf-8").strip()
                ) from exc
            raise _unavailable(f"imported board cases are unavailable: {exc}") from exc

    return cases


def _check(root: Path) -> Callable[[Request], str]:
    """Record the Candidate's attempt verbatim — grading waits for the aggregate.

    WHY no grading here: grading is the aggregate's job (through the scorer adapter), so a
    scorer bug can never poison the collected row — the Candidate's answer is always
    preserved for re-grading.
    """

    @observe_phase(ActivityKind.ANSWERING)
    def check(request: Request) -> str:
        try:
            case_id: int = positive_case_id(request.intent)
            if _grading_material(root, case_id) is None:
                # Refuse early: an attempt recorded against unusable Grading Material
                # could never be graded — fail the call, not the aggregate later.
                raise ValueError(f"the private target record for case {case_id} is unusable")
            answer = candidate_answer(request.context)
        except (OSError, TypeError, ValueError) as exc:
            # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except clause
            # mixes asset-IO and payload/definition causes; classifying needs a try-body split.
            raise _unavailable(str(exc)) from exc
        record: dict[str, Any] = {
            "schema": CHECK_SCHEMA,
            "case_id": case_id,
            "attempt": 1,
            "answer": answer.text,
            "status": answer.status,
            "refusal": answer.refusal,
            "finish_reason": answer.finish_reason,
            "execution": (
                None if answer.execution is None else answer.execution.model_dump(by_alias=True)
            ),
            # INVARIANT: absence stays absence (OME-843).
            **(
                {}
                if answer.operations is None
                else {
                    "operations": [
                        operation.model_dump(by_alias=True) for operation in answer.operations
                    ]
                }
            ),
        }
        return compact_json(record)

    def record(request: Request) -> str:
        try:
            case_id = positive_case_id(request.intent)
        except ValueError:
            return check(request)  # Preserve the existing invalid-request error translation.
        with case_scope(case_id, recording=True):
            return check(request)

    return record


def _check_surface(benchmark: ImportedBenchmark, root: Path) -> Callable[[Request], str]:
    @observe_phase(ActivityKind.GRADING)
    def check_surface(request: Request) -> str:
        if request.intent == "feedback":
            return _surface_feedback(request.context)
        if request.intent != "check":
            raise _contract_error(f"unsupported check-surface operation {request.intent!r}")
        try:
            payload = json_object(request.context, "imported board check surface")
            if set(payload) != {"input", "invocation"}:
                raise ValueError("check surface context must carry exactly input and invocation")
            input_text, invocation = payload["input"], payload["invocation"]
            if not isinstance(input_text, str) or not isinstance(invocation, str):
                raise ValueError("check surface input and invocation must be text")
            verdict = check_surface_verdict(
                benchmark, root, input_text=input_text, invocation=invocation
            )
        except (OSError, TypeError, ValueError) as exc:
            # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except clause
            # mixes asset-IO and payload/definition causes; classifying needs a try-body split.
            raise _unavailable(str(exc)) from exc
        return compact_json(verdict)

    return check_surface


def _surface_feedback(record_json: object) -> str:
    record = json_object(record_json, "imported board check-surface feedback")
    if record.get("schema") != DRAFT_FEEDBACK_SCHEMA:
        raise _contract_error(
            f"feedback input must be a {DRAFT_FEEDBACK_SCHEMA} check-surface record"
        )
    feedback = record.get("feedback")
    if not isinstance(feedback, str):
        raise _contract_error("check-surface record feedback must be text")
    return feedback


def check_surface_verdict(
    benchmark: ImportedBenchmark, root: Path, *, input_text: str, invocation: str
) -> dict[str, Any]:
    """Run the benchmark's own scorer mid-run — the §4 dual registration, second office.

    Input-addressed (the OME-796 port rule): a black-box ``$candidate`` only ever sees
    ``$input``, so the case resolves by exact prompt text. The verdict record is the
    sealed-envelope boundary — it carries pass/fail and sanitized feedback, NEVER the
    answer key or the scorer's explanation (which may quote it).

    AIDEV-NOTE: each call re-reads cases.json (linear scan) and rebuilds the
    BenchmarkAggregation + scorer + a fresh executor — fine at proof-benchmark scale, but cache a
    per-root case→id index and the scored path before a bulk import lands.
    """

    case_id: int = _case_by_input(root, input_text)
    material: Mapping[str, Any] | None = _grading_material(root, case_id)
    if material is None:
        # INVARIANT: failure wording is this plugin's published voice — refuse
        # here, or the scorer adapter's internal TypeError vocabulary reaches the candidate.
        raise ValueError(_FAILURE_MESSAGES["missing_target_asset"])
    answer: str = candidate_answer(invocation).text
    outcome: CaseGradeOutcome = _run_sync(
        benchmark.aggregation().grade_case(
            GradeRequest(
                case_id=case_id,
                input=TextPayload(text=input_text),
                answer=TextPayload(text=answer),
                row={},
                material=material,
            )
        )
    )
    if outcome.failure_code is not None:
        # .get(code, code): an unknown future scorer-adapter code stays a clean refusal,
        # never a KeyError swallowing the real cause.
        raise ValueError(_FAILURE_MESSAGES.get(outcome.failure_code, outcome.failure_code))
    assert outcome.score is not None
    passed: bool = outcome.score >= 1.0
    return {
        "schema": DRAFT_FEEDBACK_SCHEMA,
        "passed": passed,
        "satisfaction": outcome.score,
        "feedback": "" if passed else _CHECK_FEEDBACK,
        "answer": answer,
        "invocation": invocation,
    }


def benchmark_aggregate(
    benchmark: ImportedBenchmark,
    raw_case_grades: str,
    root: Path,
    *,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Score every selected Case on the shared grading, then mean accuracy."""

    return _run_sync(benchmark_aggregate_async(benchmark, raw_case_grades, root, case_ids=case_ids))


async def benchmark_aggregate_async(
    benchmark: ImportedBenchmark,
    raw_case_grades: str,
    root: Path,
    *,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    # WHY one store per call: a run's Scores live exactly as long as its aggregate, so two
    # runs (or a retried aggregate) never read each other's marks.
    kept: dict[int, Any] = {}
    metric_factory: Callable[[], Any] | None = benchmark.whole_run_metric_factory
    # WHY: Inspect scorers are already async; preserve their endpoint's log scope.
    return await benchmark.aggregation(None if metric_factory is None else kept).aggregate_async(
        raw_case_grades,
        benchmark_id=benchmark.benchmark.id,
        benchmark_revision=benchmark.benchmark.revision,
        selected_cases=read_selected_cases(
            root,
            case_ids,
            benchmark_label=benchmark.benchmark.title,
            error_type=AggregateError,
        ),
        grading_material=lambda case_id: _grading_material(root, case_id),
        scorer=_accuracy if metric_factory is None else _whole_run_tally(metric_factory(), kept),
    )


def _aggregate(
    benchmark: ImportedBenchmark, root: Path
) -> Callable[[str, int], Awaitable[dict[str, Any]]]:
    async def aggregate_handler(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        return await benchmark_aggregate_async(
            benchmark, case_evaluations, root, case_ids=tuple(range(1, selected_case_count + 1))
        )

    return aggregate_handler


def _judged_aggregate(
    benchmark: ImportedBenchmark, root: Path, node: Url4Node
) -> Callable[[str, int], Awaitable[dict[str, Any]]]:
    """The judged face: bind the judge transport, grade on the CALLER's loop."""

    async def aggregate_handler(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        # WHY the lazy import: judge_provider drags in inspect_ai; benchmark
        # registration happens at engine import in every mode, and only a judged
        # benchmark's GRADING needs the provider (the scorer adapter's own lazy-import rule).
        from screamingface_engine_inspect.judge_provider import (
            JudgeTransport,
            bound_judge_transport,
            judge_filling_model_role,
        )

        async def fetch(target: str) -> str:
            # INVARIANT (OME-1240): the judge call's only exit is THIS node's own
            # declared model route — the same connector that routes, meters, and
            # identity-stamps every candidate call serves the judge's.
            return await node.fetch(target, relative=True)

        assert benchmark.judge is not None  # the endpoint wiring picks this face
        transport = JudgeTransport(
            fetch=fetch,
            params=benchmark.judge.params,
            benchmark_id=benchmark.benchmark.id,
        )
        with ExitStack() as scope:
            scope.enter_context(bound_judge_transport(transport))
            if benchmark.judge.model_role is not None:
                # A role-based scorer asks inspect for "the grader" — answer
                # with the pinned judge, for this grading pass only (OME-1370).
                scope.enter_context(
                    judge_filling_model_role(benchmark.judge.model_role, benchmark.judge.model)
                )
            return await benchmark_aggregate_async(
                benchmark,
                case_evaluations,
                root,
                case_ids=tuple(range(1, selected_case_count + 1)),
            )

    return aggregate_handler


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Validate the envelope, then hoist attempt 1 into the shared candidate shape."""

    envelope: dict[str, Any] = decode_case_grade(grading, expected_case_id)
    attempt: Mapping[str, Any] = envelope["attempts"][0]
    return {
        "case": {
            "status": attempt.get("status"),
            "output": attempt.get("answer"),
            "finish_reason": attempt.get("finish_reason"),
            "refusal": attempt.get("refusal"),
            "execution": attempt.get("execution"),
            "operations": attempt.get("operations"),
            "metadata": {},
        },
        "attempt": dict(attempt),
    }


def _grading_material(root: Path, case_id: int) -> Mapping[str, Any] | None:
    """Read one Case's private Grading Material record; ``None`` when the asset is unusable."""

    try:
        decoded: object = json.loads(
            (root / "targets" / f"{case_id}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, Mapping) or "target" not in decoded:
        return None
    return dict(decoded)


def _case_by_input(root: Path, prompt: str) -> int:
    """Resolve the case whose prepared prompt is exactly ``prompt`` (prompts are unique)."""

    try:
        cases: object = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"imported board cases are unavailable: {exc}") from None
    if not isinstance(cases, list):
        raise ValueError("imported board cases must be a JSON array")
    matches: list[Any] = [
        case.get("id") for case in cases if isinstance(case, dict) and case.get("input") == prompt
    ]
    if len(matches) != 1 or not isinstance(matches[0], int):
        raise ValueError("the check surface input must match exactly one case")
    return matches[0]


def _accuracy(cases: Sequence[CaseResult]) -> CandidateScore:
    """Mean score over the graded Cases — the imported single-shot reduction.

    With Named Scores (OME-1268) every column is averaged over the SAME graded Cases as the
    headline, so all columns share Coverage's denominator (the adapter never half-grades a
    Case; a column one graded Case could not fill is published as unknown, never over
    fewer Cases). Worked example, 2 graded Cases: f1 1.0 and 0.334, exact 1.0 and 0.0 →
    score 0.667, scores f1 0.667, exact 0.5.
    """

    graded: list[CaseGrade] = [
        case.grade for case in cases if case.grade is not None and case.grade.score is not None
    ]
    values: list[float] = [float(grade.score) for grade in graded if grade.score is not None]
    if not values:  # pragma: no cover - a Benchmark always selects one Case
        raise AssertionError("an imported board's scorer requires at least one scored Case")
    return CandidateScore(
        score=round(sum(values) / len(values), 4),
        metrics={
            "correct": sum(1 for value in values if value >= 1.0),
            "scored_cases": len(values),
        },
        scores=_column_means(graded),
    )


def _whole_run_tally(
    metric: Callable[[list[Any]], object], kept: Mapping[int, Any]
) -> Callable[[Sequence[CaseResult]], CandidateScore]:
    """The tally clerk with the eval's own tally sheet: its inspect metric over the run.

    Think of grading as a marking room: the eval's scorer marks each Case, then the tally
    turns the marks into one headline. :func:`_accuracy` adds and divides; this hands the
    graded Cases' own inspect Scores to the eval's metric instead. Stages, in execution order:

    Stage 1 — the graded Cases only (the finalizer passes exactly those; a failed Case
              never reaches a metric, as with the mean). Each one's Score was filed by the
              scorer adapter in ``kept`` under its Case id, already reduced the way inspect
              reduces a Sample before any metric runs.
    Stage 2 — call the metric: a plain function from the same package the scorer came
              from. No ``eval()``, no solver, no model call.
    Stage 3 — publish: a number becomes the Headline Score; a dict becomes the Headline
              Score (its FIRST key, inspect's own headline rule) plus the Named Scores,
              headline first. A float metric on a row with Named Scores keeps the column
              means beside it, with the headline column carrying the metric's number.

    Worked example (contracteval's shape): 10 Cases, 7 with no related clause, and the
    Candidate always answers "no related clause". The mean is 7/10 = 0.7, because it is
    right on every empty Case. F1 counts true positives (clauses found that exist): 0,
    against 3 missed clauses, so F1 = 2·0 / (2·0 + 0 + 3) = 0.0, the eval's number.

    Raises:
        AggregateError: the headline is not a finite number up to 1, naming the metric and
            what it returned. A Headline Score is higher-is-better up to 1, so xstest's
            0..100 ``refusal_rate`` is refused, never clipped or rescaled.
    """

    # WHY the scorer helper: inspect's one registry names metrics and scorers alike, and the
    # lazy import keeps inspect out of engine start-up (only an opted-in row reaches here).
    from screamingface_engine_inspect.scorer_metrics import scorer_registry_name

    name: str = scorer_registry_name(metric)

    def tally(cases: Sequence[CaseResult]) -> CandidateScore:
        # Stage 1 — the graded Cases' kept Scores, in roll-call order.
        try:
            samples: list[Any] = [kept[int(case.case_id)] for case in cases]
        except KeyError as missing:
            raise AggregateError(f"graded Case {missing} kept no Score for {name}") from None
        # Stage 2 — the eval's own tally sheet.
        value: object = metric(samples)
        # Stage 3 — one number, or a dict whose first key heads it.
        named: dict[str, object] = dict(value) if isinstance(value, Mapping) else {}
        headline: object = next(iter(named.values()), None) if named else value
        if not _is_headline(headline):
            raise AggregateError(
                f"the whole-run metric {name} returned {headline!r}; a Headline Score is a "
                "finite number up to 1"
            )
        assert isinstance(headline, int | float)
        score: float = round(float(headline), 4)
        mean: CandidateScore = _accuracy(cases)
        scores: dict[str, float | None] = (
            {key: _named_value(item) for key, item in named.items()} if named else dict(mean.scores)
        )
        if scores and not named:
            # INVARIANT: the headline column IS `score` (the Report shows them as one number).
            scores[next(iter(scores))] = score
        return CandidateScore(score=score, metrics=mean.metrics, scores=scores)

    return tally


def _is_headline(value: object) -> bool:
    """True for a number a Candidate Result may publish as its Headline Score."""

    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value <= 1.0
    )


def _named_value(value: object) -> float | None:
    """One Named Score from a dict metric: a finite number, rounded; anything else unknown."""

    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(float(value), 4)


def _column_means(graded: Sequence[CaseGrade]) -> dict[str, float | None]:
    """Each Named Score column's mean over the graded Cases, in the headline-first order
    the first Case declares; empty when the Benchmark has no Named Scores."""

    names: tuple[str, ...] = tuple(graded[0].scores) if graded else ()
    means: dict[str, float | None] = {}
    for name in names:
        column: list[float | None] = [grade.scores.get(name) for grade in graded]
        # INVARIANT: every column shares the headline's denominator. A column one graded
        # Case could not fill (a None value) has no honest mean over those Cases, so it is
        # published as unknown — never as a mean over fewer Cases, never as 0.0.
        filled: list[float] = [float(value) for value in column if value is not None]
        means[name] = round(sum(filled) / len(filled), 4) if len(filled) == len(column) else None
    return means


def _run_sync[T](coroutine: Awaitable[T]) -> T:
    """Drive the async scorer adapter from a sync route handler (the shared grading pattern).

    WHY a verbatim copy of shared-grading ``scored._run_sync`` instead of an import: it is
    private there, and acceptance §8.2 demands ZERO shared-grading edits in this ticket —
    exporting it is a one-line core follow-up when a third caller appears.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_awaited(coroutine))
    # INVARIANT (OME-1240): a COPY of the caller's context rides into the worker
    # thread, mirroring shared-grading `scored._run_sync` verbatim — the twins must not
    # diverge on whether a judge-calling hook can see the run's usage sink.
    context = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(context.run, asyncio.run, _awaited(coroutine)).result()


async def _awaited[T](coroutine: Awaitable[T]) -> T:
    return await coroutine


__all__ = [
    "AggregateError",
    "ImportedBenchmark",
    "JudgeSpec",
    "benchmark_aggregate",
    "benchmark_aggregate_async",
    "install_imported_benchmark",
    "single_shot_benchmark",
]
