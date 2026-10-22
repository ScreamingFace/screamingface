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
import re
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Unpack

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.case_context import case_scope
from screamingface_engine.benchmarks.case_evaluation import (
    CaseCheck,
    aggregate_code,
    case_evaluation_code,
)
from screamingface_engine.benchmarks.case_records import abstain_mark, answer_abstain_mark
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_RESULT_SCHEMA,
    CaseGrade,
    CaseResult,
)
from screamingface_engine.benchmarks.definition import (
    AnswerRule,
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkOrigin,
    DifficultyTier,
    DraftFeedbackOffer,
    FailurePolicy,
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
from screamingface_engine.benchmarks.grading_endpoints import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.grading_endpoints import (
    candidate_answer,
    compact_json,
    json_object,
)
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    attempt_steps,
    evaluation_protocol,
)
from screamingface_engine.benchmarks.provenance import ProvenanceFields
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    CASE_GRADING_CONCURRENCY,
    BenchmarkAggregation,
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.case_grades import (
    CaseGradeReader,
    read_selected_cases,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload
from screamingface_engine.retrieval_policy import normalize_excluded_domains
from screamingface_engine_inspect.conversation_input import (
    conversation_input,
    conversation_messages,
)
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
from screamingface_engine_inspect.verdict_counts import run_verdict_counts
from url4 import CodeHandler, Node
from url4.peer.server import Request, Url4Node

# INVARIANT: an imported Benchmark's Candidate call is retrieval-free unless its row declares a
# retrieval policy (OME-1527, R13). Most scorers compare text to a pinned answer key, and a
# model that searched would answer a different question. A row that declares one (draco: search
# on, seven domains banned) sends it on the Candidate call, where the Candidate adapter applies
# it as a ceiling no nested call can widen; grading calls run outside that call.

# INVARIANT: failure wording is this plugin's published voice; no rubric-flavored
# codes may leak into an imported benchmark's result.
_FAILURE_MESSAGES: Mapping[str, str] = {
    "scorer_error": "the inspect scorer raised while grading this Case",
    "invalid_score_value": "the inspect scorer returned a value this board cannot map to a score",
    # WHY (OME-1527): the scorer adapter names a judge that never gave a parseable verdict
    # (`judge_redraw`); without a message here that Case crashed the whole aggregate.
    "judge_reply_invalid": "the judge gave no parseable verdict for this Case after its redraws",
    "missing_target_asset": "the baked target record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}

# WHY this text and nothing richer: mid-run feedback crosses into the candidate's
# context, so it must never carry the answer key or the scorer's explanation (which may
# quote it). Wrong-ness is the entire message; the sealed envelope holds. The one exception
# is a row the owner allowed to send its scorer's own words (``scorer_draft_feedback``):
# those come from a key the scorer fills for the Candidate, never from its explanation.
_CHECK_FEEDBACK = (
    "The committed answer does not match the expected solution. "
    "Re-derive the result step by step and commit a corrected final answer."
)

#: The ``Score.metadata`` key a scorer fills with its own Draft Feedback (OME-1527, R9):
#: ``{"satisfaction": <0..1>, "feedback": "<words for the Candidate>"}``. Read only on a row
#: that sets ``scorer_draft_feedback``; the lane forwards these two values and nothing else
#: of the Score (never its explanation, answer, other metadata, or the Case's target).
DRAFT_FEEDBACK_METADATA_KEY = "draft_feedback"

#: The longest scorer feedback a check forwards. IFEval's worst Case, every instruction
#: failed, renders 413 characters of the checker's own words (all 541 Cases measured,
#: 2026-10-13); the bound leaves room for that and refuses a scorer that dumps more.
_SCORER_FEEDBACK_MAX_CHARS = 2_000


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
        seed_per_pass: the scorer grades over judge passes and names pass ``k`` as
            ``GenerateConfig(seed=k)``; the judge call then carries ``seed=k`` after the
            pinned params, so N passes are N requests, never one cached reply (OME-1527
            R12). Benchmark identity when set. A pinned ``seed`` beside it is refused, and
            so is a judge call that names no pass.
    """

    model: str
    params: tuple[tuple[str, str], ...] = ()
    model_role: str | None = None
    seed_per_pass: bool = False

    def __post_init__(self) -> None:
        """Refuse a row that pins a seed AND gives each judge pass its own."""

        if self.seed_per_pass and any(name == "seed" for name, _ in self.params):
            raise ValueError(
                f"judge {self.model!r} pins a seed and declares seed_per_pass — each judge "
                "pass sends its own seed, so a pinned one would put two on the call; drop "
                "one (OME-1527 R12)"
            )


#: What a retrieval policy id may hold: lowercase words joined by ``/`` (``draco/reproduction``),
#: so it can never break the newline-joined revision or a generated row.
_RETRIEVAL_POLICY_ID: re.Pattern[str] = re.compile(
    r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*"
)


@dataclass(frozen=True, slots=True)
class RetrievalPolicyDeclaration:
    """A Benchmark's web-search rule for its Candidate: search on, these domains never reached.

    The exam's own rule, not the Candidate's choice (draco bans the sites that host its
    answers). The Candidate call carries it, the Candidate adapter turns it into the ceiling
    every nested model call runs under, and both fields are Benchmark identity. Checked when
    the row is declared, so a malformed one fails at import, never mid-run.

    Attributes:
        policy_id: the name a published score cites, e.g. ``draco/reproduction``.
        excluded_domains: bare domains, e.g. ``("arxiv.org", "huggingface.co")``; stored
            lowercased, deduplicated and sorted, so their order never moves the revision.
    """

    policy_id: str
    excluded_domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not _RETRIEVAL_POLICY_ID.fullmatch(
            self.policy_id
        ):
            raise ValueError(
                f"retrieval policy id {self.policy_id!r} must be lowercase words joined by /, "
                "e.g. draco/reproduction"
            )
        # WHY refuse an empty list (draco's own build rule): search with nothing banned can
        # read a public answer key, and an empty list usually means the list was lost.
        if not self.excluded_domains:
            raise ValueError(
                f"retrieval policy {self.policy_id}: excluded_domains is empty — name the "
                "domains the Candidate must never reach"
            )
        try:
            domains: tuple[str, ...] = normalize_excluded_domains(self.excluded_domains)
        except ValueError:
            raise ValueError(
                f"retrieval policy {self.policy_id}: excluded_domains must be bare domains "
                f"like arxiv.org, got {list(self.excluded_domains)!r}"
            ) from None
        object.__setattr__(self, "excluded_domains", domains)

    def revision_pins(self) -> tuple[str, str]:
        """The policy as Benchmark identity: its id and its sorted banned domains."""

        return (
            f"retrieval_policy={self.policy_id}",
            f"retrieval_excluded_domains={json.dumps(list(self.excluded_domains))}",
        )


@dataclass(frozen=True, slots=True)
class ImportedBenchmark:
    """One assembled imported benchmark — the benchmark plus its plugin-side bindings."""

    benchmark: Benchmark
    registration: BenchmarkRegistration
    scorer_factory: Callable[[], Any]
    multiple_correct: bool
    cases_route: str
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
    #: The key of a dict-returning whole-run metric that is the Headline Score; its other
    #: keys are published as run metrics (OME-1527). None for a metric returning one number,
    #: and for every row that keeps the mean. Hashed by the caller's pins.
    whole_run_headline: str | None = None
    #: The Task's own any-of-N epoch reducer as a lazy factory, for a row with Attempts that
    #: honours a whole-run metric (OME-1527 x OME-1458); None reduces each Case with inspect's
    #: default mean. Hashed by the caller's pins.
    epoch_reducer_factory: Callable[[], Any] | None = None
    #: Serve each Case's input to the Candidate as the candidate-input envelope rather than
    #: as plain text (OME-1527); False on every imported row. Hashed by the factory.
    candidate_input_envelope: bool = False
    #: Draft Feedback carries the scorer's own partial score and words, read from
    #: ``Score.metadata[DRAFT_FEEDBACK_METADATA_KEY]`` (OME-1527, R9), instead of the fixed
    #: sentence; False on every imported row. Hashed by the factory.
    scorer_draft_feedback: bool = False

    def aggregation(
        self, kept_scores: MutableMapping[int, Any] | None = None
    ) -> BenchmarkAggregation:
        """This benchmark's shared-grading binding — built on demand so the scorer stays lazy.

        ``kept_scores`` is one run's private store of the graded Cases' inspect Scores, for
        the tally of a row that honours the eval's whole-run metric; None keeps nothing.
        Each Case's Attempt Scores are filed reduced by the Task's own reducer.
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
                epoch_reducer=(
                    None if self.epoch_reducer_factory is None else self.epoch_reducer_factory()
                ),
            ),
            failure_messages=_FAILURE_MESSAGES,
            method="inspect_scorer",
            grading_failure_code="inspect_grading_failed",
            grading_failure_message="the inspect scorer pipeline could not grade this Case",
            missing_material_code="missing_target_asset",
            inverted_grade=self.inverted_grade,
            named_scores=self.named_scores,
            # WHY judged only (OME-1527, R4): a judged Case waits on a judge call, so
            # marking Cases side by side shortens the run's tail; a judge-free scorer
            # finishes at once and keeps serial marking.
            case_grading_concurrency=CASE_GRADING_CONCURRENCY if self.judge is not None else 1,
            failure_policy=self.benchmark.declaration.failure_policy,
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
    failure_policy: FailurePolicy,
    multiple_correct: bool = False,
    judge: JudgeSpec | None = None,
    inverted_grade: bool = False,
    verdict_grades: Mapping[str, float] | None = None,
    extra_scorer_factories: Sequence[Callable[[], Any]] = (),
    named_scores: Sequence[str] = (),
    origin: BenchmarkOrigin = "inspect_evals",
    whole_run_metric_factory: Callable[[], Any] | None = None,
    whole_run_headline: str | None = None,
    epoch_reducer_factory: Callable[[], Any] | None = None,
    attempts: int = 1,
    retrieval_policy: RetrievalPolicyDeclaration | None = None,
    candidate_input_envelope: bool = False,
    scorer_draft_feedback: bool = False,
    published_revision: str | None = None,
    answer_rule: AnswerRule | None = None,
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
        failure_policy: what a Case that never got a valid grade does to the score, authored
            on the BenchmarkSpec row (OME-1642); passed into the declaration verbatim.
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
        extra_scorer_factories: the Task's other scorers as lazy factories, in inspect_evals'
            order; the adapter grades each Case once per scorer (OME-1268). The caller
            carries them into ``revision_pins``.
        named_scores: the keys of the Case's Named Scores, headline first (OME-1268);
            empty on a single-scorer benchmark. The caller carries it into ``revision_pins``.
        whole_run_metric_factory: zero-arg callable returning the eval's own inspect metric,
            which then scores the whole run in place of the mean (OME-1527, R1); None keeps
            the mean. The caller carries its reference into ``revision_pins``.
        whole_run_headline: the key of a dict-returning whole-run metric that is the
            Headline Score; the dict's other keys become run metrics (OME-1527). None for a
            metric returning one number. The caller carries it into ``revision_pins``.
        epoch_reducer_factory: zero-arg callable returning the Task's own any-of-N reducer,
            which reduces each Case's Attempt Scores before the whole-run metric reads them
            (OME-1527 x OME-1458); None reduces with inspect's default mean. The caller
            carries its name into ``revision_pins``.
        attempts: Attempts per Case (OME-1458) — the expression asks each Case this many
            times and the aggregate folds them per Check. The caller carries it into
            ``revision_pins``.
        retrieval_policy: the row's web-search rule for the Candidate call (OME-1527, R13);
            None keeps the call retrieval-free. Hashed into the revision below when set.
        candidate_input_envelope: the Candidate gets each Case's input wrapped in the
            candidate-input envelope, the form a hand-built Benchmark sent (OME-1527). A
            single model sees the same chat message either way, since the connector unwraps
            the envelope; a Fusion synthesizer is pasted ``$input`` raw, so only this keeps a
            migrated Benchmark's Fusion bytes, and its recorded golden, unchanged. The scorer
            and ``cases.json`` keep plain text. Hashed into the revision below when set.
        scorer_draft_feedback: the Draft Feedback check sends the scorer's own partial
            score and words (OME-1527, R9) instead of 0-or-1 and the fixed sentence. Needs
            ``with_check_surface``, which only the owner turns on for a Benchmark. Hashed
            into the revision below when set.
        published_revision: the revision this Benchmark publishes (routes,
            ``Benchmark.revision``) instead of the computed fingerprint (OME-1527). WHY:
            published ids are what submissions and the leaderboard key on, so they are never
            moved by a computed fingerprint, only by a deliberate bump (OME-1610). Never
            compared with the fingerprint (owner decision, 2026-10-15). NOT hashed into the
            revision. None publishes the computed fingerprint.
        answer_rule: how the grader reads an answer, as pinned combine operator ids (OME-1289).
            Published in the catalog; NOT hashed into the revision (like ``focus``).

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
    if candidate_input_envelope and with_check_surface:
        # WHY: the check surface finds its Case by the exact text the Candidate was given
        # (`_case_by_input` reads cases.json), which the envelope would no longer match.
        raise ValueError(
            f"{benchmark_id}: a Benchmark serving its Candidate the input envelope cannot "
            "declare a check surface"
        )
    if scorer_draft_feedback and not with_check_surface:
        # WHY: the scorer's words only ever travel through the Draft Feedback offer; asking
        # for them without the offer is a row that misread what it turned on.
        raise ValueError(
            f"{benchmark_id}: scorer_draft_feedback needs a Draft Feedback offer "
            "(with_check_surface=True)"
        )
    if failure_policy == "withhold" and (whole_run_metric_factory is not None or inverted_grade):
        # WHY (OME-1642): a whole-run metric is not a mean of Case grades (F1 score, per-task
        # accuracy), and on a refusal-measuring row the failed Case is the behaviour the
        # Benchmark rewards, so "a failed Case counts 0" has no meaning for either until each
        # has its own rule. Whole-run-metric rows (spec §5, group F) and inverted-grade rows
        # (group E) stay coverage_declare. The message names the cause that fired.
        cause = (
            "a whole-run metric" if whole_run_metric_factory is not None else "an inverted grade"
        )
        raise ValueError(
            f"{benchmark_id}: failure_policy withhold cannot score {cause} — "
            "the row needs its own failure rule first (OME-1642)"
        )
    if (
        judge is not None
        and retrieval_policy is not None
        and ("web_search", "false") not in judge.params
    ):
        # WHY (OME-1527, R13): the policy reaches the Candidate call only. A judge call that
        # names no web_search searches whenever its route can (a route's default is on), so on a
        # searching exam it could look the answer up — the judge pins it off, as draco's does.
        raise ValueError(
            f"{benchmark_id}: a row with retrieval policy {retrieval_policy.policy_id} must pin "
            "its judge's web search off — add ('web_search', 'false') to JudgeSpec.params"
        )
    # WHY: pins are newline-joined below; a pin containing "\n" would make two
    # different pin lists hash identically — refused, never coerced.
    if any("\n" in pin for pin in revision_pins):
        raise ValueError(f"{benchmark_id}: revision_pins must not contain newlines")
    fingerprint: str = hashlib.sha256(
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
                        # WHY conditional: no published row gives its passes seeds, so
                        # every judged revision holds (OME-1527 R12).
                        *(("judge_seed_per_pass=True",) if judge.seed_per_pass else ()),
                    )
                ),
                # WHY conditional (OME-1527, R13): searching changes what the Candidate can
                # know, so the policy is identity; unset adds nothing, so no revision moves.
                *(() if retrieval_policy is None else retrieval_policy.revision_pins()),
                # WHY conditional (OME-1527): the envelope changes what a Fusion synthesizer
                # reads, so it is identity; unset adds nothing, so no imported revision moves.
                *(("candidate_input=envelope",) if candidate_input_envelope else ()),
                # WHY conditional (OME-1527, R9): what the Candidate is told mid-run is
                # identity; unset adds nothing, so no published revision moves.
                *(("draft_feedback=scorer",) if scorer_draft_feedback else ()),
                # WHY conditional (OME-1642): the denominator is Benchmark identity — a withhold
                # score is a different number from the same answers, so old and new scores never
                # share a board; coverage_declare adds nothing, so no such revision moves.
                *(("failure_policy=withhold",) if failure_policy == "withhold" else ()),
            )
        ).encode()
    ).hexdigest()[:16]
    # WHY no comparison here: a row that sets published_revision publishes it whatever the
    # fingerprint computes to, so a changed exam can never take a Benchmark down in prod
    # (OME-1527, OME-1610). Nothing checks the two agree (owner decision, 2026-10-15).
    revision: str = published_revision or fingerprint
    prefix: str = f"/benchmarks/{benchmark_id}/{revision}"
    routes: dict[str, str] = {
        "cases": f"{prefix}/cases",
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
        build=_build(routes, case_count, attempts, retrieval_policy),
        install=install,
        focus=focus,
        dataset_url=dataset_url,
        # Benchmark Provenance, baselines, notebook (OME-1455): authored on the BenchmarkSpec
        # row like `difficulty`, threaded through verbatim; shapes checked by `Benchmark`.
        answer_rule=answer_rule,
        **provenance,
        declaration=BenchmarkDeclaration(
            # WHY the row's own policy, threaded through verbatim (OME-1642): the cover sheet
            # names the rule the row declares, never a default (OME-1039).
            failure_policy=failure_policy,
            interaction="single_shot",
            # The tier is authored on the BenchmarkSpec row (the imported benchmark's one
            # authoring site) and threaded through verbatim (OME-1257).
            difficulty=difficulty,
            attempts=attempts,
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
        check_surface_route=routes["check_surface"],
        case_evaluation_route=routes["case_evaluation"],
        aggregate_route=routes["aggregate"],
        judge=judge,
        inverted_grade=inverted_grade,
        verdict_grades=verdict_grades,
        extra_scorer_factories=tuple(extra_scorer_factories),
        named_scores=tuple(named_scores),
        whole_run_metric_factory=whole_run_metric_factory,
        whole_run_headline=whole_run_headline,
        epoch_reducer_factory=epoch_reducer_factory,
        candidate_input_envelope=candidate_input_envelope,
        scorer_draft_feedback=scorer_draft_feedback,
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
        "check_surface": benchmark.check_surface_route,
        "case_evaluation": benchmark.case_evaluation_route,
        "aggregate": benchmark.aggregate_route,
    }
    install_cases(node, routes["cases"], _cases(root, envelope=benchmark.candidate_input_envelope))
    # Spec R1: the per-Case and per-run steps are code the expression points at.
    code: tuple[tuple[str, CodeHandler], ...] = (
        (
            routes["case_evaluation"],
            case_evaluation_code(
                label=f"{benchmark.benchmark.title} Case evaluation",
                check=_check(root),
                build_case_grade=build_case_grade,
                # WHY: imported benchmarks only package the Attempt here; their scorer runs
                # in the aggregate.
                observe_grading=False,
            ),
        ),
        (
            routes["aggregate"],
            # WHY: both scorer families stay on the owning loop for logs and model I/O.
            aggregate_code(
                label=benchmark.benchmark.title,
                available_case_count=benchmark.benchmark.case_count,
                aggregate=(
                    _judged_aggregate(benchmark, root, node)
                    if benchmark.judge is not None
                    else _aggregate(benchmark, root)
                ),
            ),
        ),
    )
    for path, handler in code:
        if not node.has_code(path):
            node.code(path)(handler)
    if benchmark.benchmark.check_surface is not None and routes["check_surface"] not in set(
        node.processor_routes()
    ):
        # Spec §4 — the SAME scorer, second office hour: the advertised
        # check-surface port for the corrective loop.
        node.endpoint(routes["check_surface"])(_check_surface(benchmark, root))


def _build(
    routes: Mapping[str, str],
    available: int,
    attempts: int = 1,
    retrieval_policy: RetrievalPolicyDeclaration | None = None,
) -> Callable[[int], Node]:
    """The canonical one-answer-per-Attempt expression, graded once in the aggregate.

    Each Case asks the Candidate ``$item.input`` once per Attempt (OME-1458), then the
    ``case-evaluation`` code records every Attempt and ``aggregate`` grades the run. A
    ``retrieval_policy`` turns search on for the Candidate call with its banned domains;
    without one the call says ``web_search=false``, as it always has.
    """

    banned: tuple[str, ...] = () if retrieval_policy is None else retrieval_policy.excluded_domains

    def build(case_count: int) -> Node:
        return evaluation_protocol(
            cases_route=routes["cases"],
            steps=attempt_steps(
                "$item.input",
                attempts=attempts,
                case_count=case_count,
                web_search=retrieval_policy is not None,
                web_search_exclude=banned,
            ),
            case_terminal=routes["case_evaluation"],
            run_terminal=routes["aggregate"],
            selected_case_count=case_count,
            available_case_count=available,
        )

    return build


def _cases(root: Path, *, envelope: bool = False) -> Callable[[], str]:
    """The cases route: ``cases.json`` as written, or with each input enveloped."""

    @observe_phase(ActivityKind.CASE_LOADING)
    def cases() -> str:
        try:
            text: str = (root / "cases.json").read_text(encoding="utf-8")
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
        return _enveloped_inputs(text) if envelope else text

    return cases


def _enveloped_inputs(cases_json: str) -> str:
    """Wrap every Case's plain input in the candidate-input envelope, byte for byte as a
    hand-built Benchmark's preparer wrote it (OME-1527).

    Worked example: input ``"Draft the memo."`` is served as
    ``{"schema":"screamingface.candidate-input.v1","messages":[{"role":"user","content":
    "Draft the memo."}]}`` — compact separators, non-ASCII kept as is, which is what
    hand-built gdpval's ``case_input`` wrote, so the Candidate call's bytes do not move. A
    conversation Case (R14) is already that envelope and is served as written, never wrapped
    twice.
    """

    rows: list[dict[str, Any]] = json.loads(cases_json)
    for row in rows:
        if conversation_messages(row["input"]) is None:
            row["input"] = conversation_input([{"role": "user", "content": row["input"]}])
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _check(root: Path) -> CaseCheck:
    """Record the Candidate's attempt verbatim — grading waits for the aggregate.

    WHY no grading here: grading is the aggregate's job (through the scorer adapter), so a
    scorer bug can never poison the collected row — the Candidate's answer is always
    preserved for re-grading.
    """

    @observe_phase(ActivityKind.ANSWERING)
    def check(case_id: int, invocation: str) -> dict[str, Any]:
        try:
            if _grading_material(root, case_id) is None:
                # Refuse early: an attempt recorded against unusable Grading Material
                # could never be graded — fail the call, not the aggregate later.
                raise ValueError(f"the private target record for case {case_id} is unusable")
            answer = candidate_answer(invocation)
        except (OSError, TypeError, ValueError) as exc:
            # AIDEV-NOTE (OME-1234): deliberate leftover on the catch-all — this except clause
            # mixes asset-IO and payload/definition causes; classifying needs a try-body split.
            raise _unavailable(str(exc)) from exc
        return {
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
            **answer_abstain_mark(answer),
        }

    def record(case_id: int, invocation: str, others: Mapping[str, object]) -> dict[str, Any]:
        with case_scope(case_id, recording=True):
            return check(case_id, invocation)

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
    answer key or the scorer's explanation (which may quote it). On a row with
    ``scorer_draft_feedback`` the satisfaction and the words are the ones the scorer wrote
    for the Candidate (:func:`_scorer_draft_feedback`), still never its explanation.

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
    satisfaction: float = outcome.score
    feedback: str = "" if passed else _CHECK_FEEDBACK
    if benchmark.scorer_draft_feedback:
        satisfaction, words = _scorer_draft_feedback(outcome, passed)
        feedback = "" if passed else words
    return {
        "schema": DRAFT_FEEDBACK_SCHEMA,
        "passed": passed,
        "satisfaction": satisfaction,
        "feedback": feedback,
        "answer": answer,
        "invocation": invocation,
    }


def _scorer_draft_feedback(outcome: CaseGradeOutcome, passed: bool) -> tuple[float, str]:
    """Take the partial score and words a scorer wrote for the Candidate, and check them.

    Think of it as a sealed envelope the examiner marks "may be handed to the student":
    the lane opens only that envelope. Everything else the examiner wrote (the
    explanation, the answer it extracted, its other notes, and the Case's target) stays
    in the marking room, because only this one key is read.

    Stages, in execution order:

    1. Find the envelope: ``Score.metadata[DRAFT_FEEDBACK_METADATA_KEY]`` of the headline
       scorer, as the scorer adapter copied it onto the Case's first Check.
    2. Check its shape: exactly ``satisfaction`` and ``feedback``; a number in [0, 1] that
       agrees with the verdict (a passing draft is fully satisfied, a failing one is not);
       words no longer than ``_SCORER_FEEDBACK_MAX_CHARS``, and present when the draft
       fails, since the loop needs something to react to.
    3. Refuse anything else by raising ``ValueError``. The check route turns that into
       ``benchmark_unavailable``; the message names the problem, never the scorer's text.

    Worked example (IFEval, 1 of 3 instructions met): metadata ``{"draft_feedback":
    {"satisfaction": 0.3333, "feedback": "The answer failed these requirements: ..."}}``
    → ``(0.3333, "The answer failed these requirements: ...")``; the strict headline 0.0
    still decides ``passed``.

    Args:
        outcome: the Case's graded outcome from the scorer adapter.
        passed: the verdict, from the Case score.

    Returns:
        The satisfaction and the feedback words, both safe to send as the scorer wrote them.
    """

    # Stage 1 — the one key this lane reads.
    evidence: Mapping[str, Any] = outcome.checks[0]["evidence"][0]
    envelope: object = evidence.get("metadata", {}).get(DRAFT_FEEDBACK_METADATA_KEY)
    # Stage 2-3 — its shape, or a refusal that quotes nothing the scorer wrote.
    if not isinstance(envelope, Mapping) or set(envelope) != {"satisfaction", "feedback"}:
        raise ValueError(
            f"the scorer's Score.metadata[{DRAFT_FEEDBACK_METADATA_KEY!r}] must hold exactly "
            "satisfaction and feedback"
        )
    satisfaction: object = envelope["satisfaction"]
    words: object = envelope["feedback"]
    if (
        isinstance(satisfaction, bool)
        or not isinstance(satisfaction, int | float)
        or not 0.0 <= satisfaction <= 1.0
    ):
        raise ValueError("the scorer's draft-feedback satisfaction must be a number in [0, 1]")
    if (satisfaction >= 1.0) != passed:
        raise ValueError(
            "the scorer's draft-feedback satisfaction disagrees with its verdict "
            "(only a passing draft is fully satisfied)"
        )
    if not isinstance(words, str) or len(words) > _SCORER_FEEDBACK_MAX_CHARS:
        raise ValueError(
            f"the scorer's draft-feedback words must be text of at most "
            f"{_SCORER_FEEDBACK_MAX_CHARS} characters"
        )
    if not passed and not words.strip():
        raise ValueError("the scorer gave no draft-feedback words for a failing draft")
    return float(satisfaction), words


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
        scorer=(
            _accuracy
            if metric_factory is None
            else _whole_run_tally(metric_factory(), kept, benchmark.whole_run_headline)
        ),
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
            seed_per_pass=benchmark.judge.seed_per_pass,
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
            # The abstain mark rides the hoisted row (OME-1289).
            **abstain_mark(attempt),
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
    """Mean score over the Cases the scorer is given — the imported single-shot reduction.

    FEATURE (OME-1642): under ``coverage_declare`` the finalizer hands this only the graded
    Cases, so the mean is over graded Cases exactly as before. Under ``withhold`` it hands
    every selected Case, and a Case with no numeric grade adds 0 to the headline and to every
    Named Score column — the denominator is the number of Cases given. ``scored_cases``,
    ``correct`` and the verdict counts stay over the graded Cases.

    With Named Scores (OME-1268) every column is averaged over the SAME Cases as the
    headline, so all columns share one denominator (the adapter never half-grades a
    Case; a column one graded Case could not fill is published as unknown, never over
    fewer Cases). Worked example, 2 graded Cases under ``coverage_declare``: f1 1.0 and 0.334,
    exact 1.0 and 0.0 → score 0.667, scores f1 0.667, exact 0.5. Under ``withhold``, with a
    third Case that failed: score 0.4447, scores f1 0.4447, exact 0.3333.

    A judging scorer's verdict counts (``verdicts_expected`` / ``accepted`` / ``rejected``,
    OME-1527 row 18b) are added up over the graded Cases, so the Report can warn when
    grading did not fully land; a row whose scorer writes none publishes none.
    """

    graded: list[CaseGrade] = [
        case.grade for case in cases if case.grade is not None and case.grade.score is not None
    ]
    values: list[float] = [float(grade.score) for grade in graded if grade.score is not None]
    if not values:  # pragma: no cover - a Benchmark always selects one Case
        raise AssertionError("an imported board's scorer requires at least one scored Case")
    return CandidateScore(
        score=round(sum(values) / len(cases), 4),
        metrics={
            "correct": sum(1 for value in values if value >= 1.0),
            "scored_cases": len(values),
            **run_verdict_counts(grade.metrics for grade in graded),
        },
        scores=_column_means(graded, len(cases)),
    )


def _whole_run_tally(
    metric: Callable[[list[Any]], object],
    kept: Mapping[int, Any],
    headline_key: str | None = None,
) -> Callable[[Sequence[CaseResult]], CandidateScore]:
    """The tally clerk with the eval's own tally sheet: its inspect metric over the run.

    Think of grading as a marking room: the eval's scorer marks each Case, then the tally
    turns the marks into one headline. :func:`_accuracy` adds and divides; this hands the
    graded Cases' own inspect Scores to the eval's metric instead. Stages, in execution order:

    Stage 1 — the graded Cases only. The finalizer passes exactly those because the
              withhold guard in ``single_shot`` (OME-1642) keeps every whole-run row on
              ``coverage_declare``, so a failed Case never reaches a metric, as with the
              ``coverage_declare`` mean. Each one's Score was filed by the
              scorer adapter in ``kept`` under its Case id, already reduced the way inspect
              reduces a Sample before any metric runs. For a Case asked several times
              (Attempts), that is the Task's own any-of-N reducer over its Attempt Scores.
              An abstained Case (OME-1289) is handed over at 0.0, the score its Case Result
              shows whatever the judge said, with the kept Score's metadata; when its grader
              failed, so inspect filed no Score, a bare 0.0 Score stands in. Every Case's
              Score must then equal its Case Result's score, so the metric and the Report
              read one number per Case.
    Stage 2 — call the metric: a plain function from the same package the scorer came
              from. No ``eval()``, no solver, no model call. It is third-party code, so
              anything it raises (a metadata key the Cases lack) fails the tally by the
              metric's name, never as a bare exception.
    Stage 3 — publish: a number becomes the Headline Score. A dict (the paper's F1
              beside its precision, recall and counts) must have the key the row names as
              its headline (``whole_run_headline``): that value is the Headline Score, and
              every other key joins the run's ``metrics`` beside the tally's own
              ``correct`` and ``scored_cases``. A key never becomes a Named Score of its
              own: a Named Score is a column every graded Case carries, and precision has
              no per-Case value. A row with Named Scores keeps the column means beside the
              headline, with the headline column carrying the metric's number, and so does
              any column whose name the dict also returns (ifeval's instruction-level
              accuracy is pooled over the run's instructions, not a mean of Case fractions).

    Worked example (contracteval's shape): 10 Cases, 7 with no related clause, and the
    Candidate always answers "no related clause". The mean is 7/10 = 0.7, because it is
    right on every empty Case. F1 counts true positives (clauses found that exist): 0,
    against 3 missed clauses, so F1 = 2·0 / (2·0 + 0 + 3) = 0.0, the eval's number. Had the
    metric returned ``{"f1": 0.0, "recall": 0.0, "true_negatives": 7}`` on a row naming
    ``f1``, the headline is 0.0 and ``metrics`` gains ``recall`` 0.0 and ``true_negatives`` 7.

    Raises:
        AggregateError: naming the metric, when it asks inspect for unreduced Scores (the
            store holds reduced ones, so it would read numbers inspect never hands it), when
            a graded Case that did not abstain kept no Score, when a Case's Score disagrees
            with its Case Result's score (``pass_at_2`` over a Case whose second Attempt
            failed reduces to nan, as in inspect), when it
            raises, or when its headline is not a finite number up to 1. A Headline Score
            is higher-is-better up to 1, so xstest's 0..100 ``refusal_rate`` is refused,
            never clipped or rescaled. For a dict, also when the row names no headline key,
            when the dict lacks that key, when another key's value is not a finite number,
            or when another key is one the tally already publishes (``correct``), which is
            never overwritten. A number on a row that names a headline key is refused too:
            the row says the metric returns a dict, so one of the two is wrong.
    """

    # WHY the scorer helper: inspect's one registry names metrics and scorers alike, and the
    # lazy import keeps inspect out of engine start-up (only an opted-in row reaches here).
    from screamingface_engine_inspect.scorer_metrics import (
        reads_unreduced_scores,
        scorer_registry_name,
    )

    name: str = scorer_registry_name(metric)
    # WHY refuse before grading: inspect hands an "unreduced" metric each Sample's raw Score
    # ("C"), and the store keeps the reduced one (1.0); the importer refuses it too.
    if reads_unreduced_scores(metric):
        raise AggregateError(
            f"the whole-run metric {name} asks for unreduced Scores, which the tally does "
            "not keep; keep the mean for this row"
        )

    def tally(cases: Sequence[CaseResult]) -> CandidateScore:
        # Stage 1 — the graded Cases' Scores, in roll-call order; an abstained Case's is 0.0,
        # the score its Case Result shows (OME-1289), kept Score or not.
        samples: list[Any] = [_metric_sample(case, kept, name) for case in cases]
        _check_scores_agree(cases, samples, name)
        # Stage 2 — the eval's own tally sheet. WHY catch everything: the metric is the
        # eval's code, and a bare KeyError after every Candidate call is paid names nothing.
        try:
            value: object = metric(samples)
        except Exception as exc:
            raise AggregateError(
                f"the whole-run metric {name} failed: {type(exc).__name__}: {exc}"
            ) from exc
        # Stage 3 — the headline, and a dict's other keys as run metrics (never Named
        # Scores: no Case carries a precision).
        headline, run_metrics = _headline_and_run_metrics(value, headline_key, name)
        if not _is_headline(headline):
            raise AggregateError(
                f"the whole-run metric {name} returned {headline!r}; a Headline Score is a "
                "finite number up to 1"
            )
        assert isinstance(headline, int | float)
        score: float = round(float(headline), 4)
        mean: CandidateScore = _accuracy(cases)
        return CandidateScore(
            score=score,
            metrics=_beside(mean.metrics, run_metrics, name),
            scores=_metric_columns(mean.scores, score, run_metrics),
        )

    return tally


def _metric_columns(
    column_means: Mapping[str, float | None],
    score: float,
    run_metrics: Mapping[str, int | float],
) -> dict[str, float | None]:
    """The Named Score columns beside a whole-run headline: the metric's numbers where it has them.

    INVARIANT: the headline column IS ``score`` (the Report shows them as one number). A column
    the metric's dict also names is the metric's number, rounded to 4 places, never the mean of
    the Cases' values: ifeval pools its instructions, so Case A meeting 1 of 1 and Case B 0 of 3
    is 0.25, where the mean of the Case fractions says 0.5. Every other column keeps its mean.
    """

    scores: dict[str, float | None] = dict(column_means)
    if scores:
        scores[next(iter(scores))] = score
    for column in scores:
        if column in run_metrics:
            scores[column] = round(float(run_metrics[column]), 4)
    return scores


def _headline_and_run_metrics(
    value: object, headline_key: str | None, metric_name: str
) -> tuple[object, dict[str, int | float]]:
    """Split a whole-run metric's value into its headline and the run metrics beside it.

    A number is all headline. A dict gives up the row's named key as the headline and keeps
    every other key as a run metric: ``{"f1": 0.6667, "recall": 0.6}`` with ``f1`` named →
    headline 0.6667, run metrics ``{"recall": 0.6}``. The headline's own checks (finite, up
    to 1) are the caller's; this checks only what the dict form adds.
    """

    if not isinstance(value, Mapping):
        if headline_key is not None:
            raise AggregateError(
                f"the whole-run metric {metric_name} returned {value!r}, but the row names "
                f"whole_run_headline={headline_key!r} as if it returned a dict; drop "
                "whole_run_headline"
            )
        return value, {}
    keys: str = ", ".join(map(str, value))
    if headline_key is None:
        raise AggregateError(
            f"the whole-run metric {metric_name} returned a dict ({keys}); name the key that "
            "is the Headline Score with the row's whole_run_headline, and the other keys are "
            "published as run metrics"
        )
    if headline_key not in value:
        raise AggregateError(
            f"the whole-run metric {metric_name} returned a dict ({keys}) with no "
            f"{headline_key!r}, the row's whole_run_headline"
        )
    run_metrics: dict[str, int | float] = {}
    for key, number in value.items():
        if key == headline_key:
            continue
        # WHY finite numbers only: a run metric is read as a number beside the headline; a
        # nan or a word published under the eval's name would be the wrong number silently.
        if (
            not isinstance(number, int | float)
            or isinstance(number, bool)
            or not math.isfinite(number)
        ):
            raise AggregateError(
                f"the whole-run metric {metric_name} returned {key}={number!r}; a run metric "
                "is a finite number"
            )
        run_metrics[str(key)] = number
    return value[headline_key], run_metrics


def _beside(
    tally_metrics: Mapping[str, Any], run_metrics: Mapping[str, int | float], metric_name: str
) -> dict[str, Any]:
    """The tally's own run metrics, then the whole-run metric's; a shared key is refused.

    WHY refuse, never overwrite: ``correct`` and ``scored_cases`` are the tally's own count of
    the Cases it saw; a metric's key of the same name would silently replace it.
    """

    collisions: list[str] = sorted(set(run_metrics) & set(tally_metrics))
    if collisions:
        raise AggregateError(
            f"the whole-run metric {metric_name} returned {', '.join(collisions)}, which the "
            "tally already publishes; rename the metric's key"
        )
    return {**tally_metrics, **run_metrics}


def _metric_sample(case: CaseResult, kept: Mapping[int, Any], metric_name: str) -> Any:
    """The Score one graded Case hands the whole-run metric: its kept Score, or 0.0 when it
    abstained (OME-1289), the score its Case Result shows whatever the judge said.

    WHY an abstained Case needs no kept Score: the abstain rule keeps it at 0.0 even when its
    grader failed, and then inspect filed none; the run must not stop after every model call
    is paid. Any other graded Case without one is a filing bug, refused by the metric's name.

    CONTRACT for a metric that reads verdicts from the Score metadata instead of the value
    (ifeval pools ``metadata["instructions"]``): the zeroed Score keeps the grader's real
    verdicts there, so such a metric must count a Score whose metadata carries
    ``candidate_abstained: True`` as failing every verdict, or it would credit an abstain.
    """

    from screamingface_engine_inspect.scorer_metrics import zero_sample_score

    case_id: int = int(case.case_id)
    if case.abstained:
        return zero_sample_score(kept.get(case_id), case_id)
    if case_id not in kept:
        raise AggregateError(f"graded Case {case_id} kept no Score for {metric_name}")
    return kept[case_id]


def _check_scores_agree(
    cases: Sequence[CaseResult], samples: Sequence[Any], metric_name: str
) -> None:
    """Refuse a graded Case whose Score is not the score its Case Result shows.

    INVARIANT (OME-1527): the metric and the Report read one number per Case, so any split
    fails by the metric's name here rather than publish a headline no Case Result explains.
    Attempts (OME-1458) can split them: the fold credits a Check met by any graded Attempt,
    and inspect's any-of-N reducers compute the same over 0/1 Attempt Scores, except
    ``pass_at(2)`` over a Case whose second Attempt failed, which inspect reduces to nan while
    the fold scores the graded one. So can any rewrite of a Case score the tally does not
    also hand the metric (the abstain rule's 0.0 is handed over in Stage 1 of the tally). The
    Score is read as the scorer adapter read it for the Case Result, a dict value by its
    headline column (the first Named Score), never by inspect's ``value_to_float``, which
    reads a whole dict as 0.0. The Case score is rounded to 4 places, so the Score is
    compared at that precision.
    """

    from screamingface_engine_inspect.scorer_adapter import whole_run_grade

    for case, sample in zip(cases, samples, strict=True):
        if case.grade is None:
            continue
        # The Named Scores are published headline first, so the first is the dict's headline.
        headline_name: str | None = next(iter(case.grade.scores), None)
        grade: float | None = whole_run_grade(sample.score.value, headline_name)
        if grade is not None and round(grade, 4) == case.grade.score:
            continue
        value: object = (
            sample.score.value.get(headline_name)
            if isinstance(sample.score.value, Mapping)
            else sample.score.value
        )
        if case.attempts is not None:
            raise AggregateError(
                f"graded Case {case.case_id}'s Attempts reduce to {value} for {metric_name}, "
                f"but fold to {case.grade.score}; the metric would read a number the Case "
                "Result does not show"
            )
        raise AggregateError(
            f"graded Case {case.case_id}'s Score is {value} for {metric_name}, but its Case "
            f"Result shows {case.grade.score}; the metric would read a number the Case "
            "Result does not show"
        )


def _is_headline(value: object) -> bool:
    """True for a number a Candidate Result may publish as its Headline Score."""

    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value <= 1.0
    )


def _column_means(graded: Sequence[CaseGrade], case_count: int) -> dict[str, float | None]:
    """Each Named Score column's sum over the graded Cases divided by ``case_count``, the Cases
    the scorer was given (the ungraded ones add 0), in the headline-first order the first
    graded Case declares; empty when the Benchmark has no Named Scores."""

    names: tuple[str, ...] = tuple(graded[0].scores) if graded else ()
    means: dict[str, float | None] = {}
    for name in names:
        column: list[float | None] = [grade.scores.get(name) for grade in graded]
        # INVARIANT: every column shares the headline's denominator. A column one graded
        # Case could not fill (a None value) has no honest mean over those Cases, so it is
        # published as unknown — never as a mean over fewer Cases, never as 0.0. A Case
        # with no grade at all (`withhold`, OME-1642) is a failed Case, not an unfilled
        # column: it adds 0.0 to every column, as it does to the headline.
        filled: list[float] = [float(value) for value in column if value is not None]
        means[name] = round(sum(filled) / case_count, 4) if len(filled) == len(column) else None
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
    "DRAFT_FEEDBACK_METADATA_KEY",
    "AggregateError",
    "ImportedBenchmark",
    "JudgeSpec",
    "RetrievalPolicyDeclaration",
    "benchmark_aggregate",
    "benchmark_aggregate_async",
    "install_imported_benchmark",
    "single_shot_benchmark",
]
