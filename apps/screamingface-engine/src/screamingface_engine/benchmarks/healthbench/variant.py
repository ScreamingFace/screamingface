"""How ANY HealthBench benchmark is built — identity, addresses, and the one expression tree.

Think of it as printing a benchmark paper from a template. The template is fixed: the same
dataset, the same physician rubric, the same AI judge, the same grading chain. What the
printer varies per benchmark is only three things:

    which Cases this benchmark asks    (``case_ids``)
    how it totals the papers       (``mean`` — the challenge metric, or the official clip)
    what it calls itself           (``id`` — which decides every route address)

Everything else is derived. ``variant_revision`` fingerprints the whole benchmark identity into a
16-hex revision; ``Routes`` hangs the six protocol routes plus the draft-feedback offer under
``/benchmarks/<id>/<revision>/``; ``build_variant_protocol`` writes the url4 expression tree.
``healthbench_benchmark`` is the one call a benchmark module makes.

INVARIANT: two benchmarks built here share the prepared assets and differ ONLY where the three
knobs above differ. A benchmark's revision changes if ANY hashed input changes, so an
expression addressed to an old revision physically cannot resolve against a new benchmark.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Unpack

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    DifficultyTier,
    candidate,
)
from screamingface_engine.benchmarks.healthbench import verdict
from screamingface_engine.benchmarks.healthbench.prompts import GRADER_TEMPLATE
from screamingface_engine.benchmarks.healthbench.revision_inputs import (
    CHECK_CRITERION,
    DATASET,
    DATASET_REVISION,
    JUDGE_MODEL,
    JUDGE_PARAMS,
    JUDGE_RETRIES,
    PREPARER_REVISION,
)
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    early_result,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.provenance import ProvenanceFields
from url4 import Node, RelExpr, Text, expr, iterate, render, src, struct
from url4.peer.server import Url4Node

type VariantMean = Callable[[Sequence[float]], float | None]

ASSET_BUNDLE_ID = "healthbench"


@dataclass(frozen=True, slots=True)
class Routes:
    """The seven addresses one benchmark answers on, all under its own revision prefix."""

    prefix: str
    cases: str
    judge_requests: str
    verdict: str
    rubric_evaluation: str
    case_evaluation: str
    aggregate: str
    check_surface: str

    @classmethod
    def for_variant(cls, benchmark_id: str, revision: str) -> Routes:
        prefix = f"/benchmarks/{benchmark_id}/{revision}"
        return cls(
            prefix=prefix,
            cases=f"{prefix}/cases",
            judge_requests=f"{prefix}/rubric-tasks",
            verdict=f"{prefix}/rubric-verdict",
            rubric_evaluation=f"{prefix}/rubric-evaluation",
            case_evaluation=f"{prefix}/case-evaluation",
            aggregate=f"{prefix}/aggregate",
            check_surface=f"{prefix}/check-surface/{CHECK_CRITERION}",
        )


@dataclass(frozen=True, slots=True)
class HealthbenchVariant:
    """One HealthBench identity: which Cases, which final mean, at which addresses.

    This is what the runtime needs to serve a benchmark — it carries no metadata a human
    reads (that lives on the ``Benchmark``), only what the protocol handlers consume.
    """

    id: str
    case_ids: tuple[int, ...]
    revision: str
    routes: Routes
    mean: VariantMean


def variant_revision(*, protocol_revision: str, selection_sha: str, scoring: str) -> str:
    """Fingerprint one benchmark identity into the 16 hex characters its routes carry.

    Everything a Candidate's score depends on goes in: the dataset pin, the preparer that
    turned it into assets, the shared evaluation protocol, the Candidate result schema,
    the judge pinning, the grader-template bytes — plus the three per-benchmark inputs. Change
    any of them and every route address moves, which is the only safe way to change an
    benchmark.
    """

    return hashlib.sha256(
        "\n".join(
            (
                DATASET,
                DATASET_REVISION,
                protocol_revision,
                EVALUATION_PROTOCOL_REVISION,
                CANDIDATE_RESULT_SCHEMA,
                PREPARER_REVISION,
                selection_sha,
                JUDGE_MODEL,
                repr(JUDGE_PARAMS),
                str(JUDGE_RETRIES),
                GRADER_TEMPLATE,
                scoring,
            )
        ).encode()
    ).hexdigest()[:16]


def case_ids_sha(case_ids: Sequence[int]) -> str:
    """The revision-participating fingerprint of a benchmark's Engine Case-id selection."""

    return hashlib.sha256("\n".join(str(case_id) for case_id in case_ids).encode()).hexdigest()


def build_variant_protocol(routes: Routes, case_count: int, available_case_count: int) -> Node:
    """Build the whole benchmark as one url4 expression tree (a recipe, not a run).

    Think of it as a benchmark pipeline, written inside-out because each stage is
    nested in the next. Reading outside-in, the Engine will:

    1. Fetch the Cases (patient conversations) from ``routes.cases``, and for each:
    2. Ask the Candidate model to answer the conversation, then fetch that Case's
       rubric items ("did the answer mention X?") from ``routes.tasks`` — one judge
       task per rubric item, each carrying the Candidate's answer pre-rendered
       into a grader prompt.
    3. For each rubric item, send the grader prompt to the judge model as a single
       user message (empty intent = no system row, matching the official judge),
       and parse its yes/no verdict via ``routes.verdict``. A malformed reply
       raises, so ``;retry=`` re-resolves the NESTED judge call — a fresh sample
       per attempt. That is why the judge call sits inside the verdict expression:
       as a sibling, a malformed-but-successful model call would never be retried.
    4. Roll verdicts up: rubric rows → ``routes.rubric_evaluation`` → per-Case score
       at ``routes.case_evaluation`` → all Case rows into ``routes.aggregate``, which
       computes this benchmark's benchmark-level mean. Rows travel as context, not argv, so
       no OS argument-length limit can truncate them.

    ``case_count`` < ``available_case_count`` slices to a partial run (the SDK's
    ``limit=N``); equality means the full set. Every route is revision-pinned.

    Args:
        routes: this benchmark's revision-pinned addresses.
        case_count: how many Cases this run executes (the SDK's ``limit``).
        available_case_count: how many Cases the benchmark holds in total.

    Returns:
        The unresolved DAG — the Engine executes it at submission time.
    """

    candidate_invocation = candidate(
        "$item.input",
        case_id="$item.id",
        case_index="$index",
        case_count=str(case_count),
        web_search=False,
    )
    # Stage 3a — the judge call: send one pre-rendered grader prompt to the judge model.
    # One judge pass per rubric item — the reference grades each item exactly once.
    # INVARIANT: the judge call's intent is EMPTY (`!''`). The Runner maps a non-empty
    # intent to a SYSTEM message, and the official professional judge sends no system
    # row — the entire pre-rendered GRADER_TEMPLATE is its one user message.
    judge_reply = RelExpr(
        path=_model_route(JUDGE_MODEL),
        context="$item.grader_prompt",
        intent=Text(""),
        params=JUDGE_PARAMS,
    )
    # Stage 3b — one graded rubric item: judge reply → parsed verdict → stored row.
    rubric_evaluation = expr(
        # Carry the raw Case and rubric records along (weight 0.0 = data, not scored).
        src("$item.case_record", name="case_record", weight=0.0),
        src("$item.rubric_record", name="rubric_record", weight=0.0),
        # WHY nested, not siblings: the verdict route RAISES a transient error on a
        # malformed reply, and its `;retry=` re-resolves the nested judge call — a
        # fresh sample per attempt (verdict.call docstring). Sibling wiring would
        # retry nothing: a malformed reply is a successful model call.
        verdict.call(
            judge_reply,
            case_id="$item.case_id",
            rubric_id="$item.rubric_id",
            route=routes.verdict,
            retry=JUDGE_RETRIES,
        ),
        # Post {case, rubric, verdict} to the rubric-evaluation route → one scored row.
        src(
            RelExpr(
                path=routes.rubric_evaluation,
                context=render(
                    struct(
                        {
                            "case": "$case_record",
                            "rubric": "$rubric_record",
                            "evidence": "$verdict",
                        }
                    )
                ),
                intent=Text("$item.case_id"),
            ),
            name="rubric_evaluation",
            weight=0.0,
        ),
        intent=Text("$rubric_evaluation"),
    )
    # Stage 2 — per Case: call the Candidate once, fan out one judge request per rubric item.
    rubric_items = iterate(
        RelExpr(
            path=routes.judge_requests,
            # This collection boundary invokes the Candidate exactly once per Case,
            # then fans out one pre-rendered judge request per rubric item.
            context="$candidate_invocation",
            intent=Text("$item.case_id"),
        ),
        body=(src(rubric_evaluation, name="evaluated", weight=0.0),),
        intent=Text("$evaluated"),
        # WHY fail, not the collect default (OME-924): a failed rubric-item judge branch
        # (e.g. an upstream 429, or judge_reply_invalid after its bounded retries) must
        # surface as ITS OWN error at the case-execution boundary, not be collected into
        # the rubric-row list — where the case-evaluation route would decode the error
        # object as a typed grading record and mask the real failure. The shared
        # preserve_candidate_outcome() boundary still collects this error per Case, so one
        # bad rubric item fails only that Case, with the Candidate answer intact.
        on_error="fail",
    )
    # Stage 4a — roll a Case's rubric rows up into one per-Case score.
    case_evaluation = expr(
        src(rubric_items, name="rubric_rows", weight=0.0),
        src(
            RelExpr(
                path=routes.case_evaluation,
                context="$rubric_rows",
                intent=Text("$item.case_id"),
            ),
            name="case_evaluation",
            weight=0.0,
        ),
        intent=Text("$case_evaluation"),
    )
    return build_evaluation_protocol(
        cases_route=routes.cases,
        case_evaluation=early_result(
            preserve_candidate_outcome(
                candidate_invocation=candidate_invocation,
                grading=case_evaluation,
                case_id="$item.id",
            ),
            aggregate_route=routes.aggregate,
            selected_case_count=case_count,
        ),
        selected_case_count=case_count,
        available_case_count=available_case_count,
        aggregate_route=routes.aggregate + "/graded",
    )


def healthbench_benchmark(
    *,
    id: str,
    title: str,
    description: str,
    case_ids: tuple[int, ...],
    protocol_revision: str,
    scoring: str,
    mean: VariantMean,
    selection_sha: str,
    difficulty: DifficultyTier,
    focus: str | None = None,
    dataset_url: str | None = None,
    **provenance: Unpack[ProvenanceFields],
) -> tuple[HealthbenchVariant, Benchmark]:
    """Wire one HealthBench benchmark: identity → addresses → expression → private routes.

    Args:
        id: the public benchmark id; it becomes the first path segment of every route.
        title: the human name shown in the catalogue.
        description: the catalogue description — it must say which metric this benchmark
            reports, because that is the difference a reader cannot see anywhere else.
        case_ids: the Engine Case ids this benchmark serves, in serve order.
        protocol_revision: this benchmark's own protocol version string (hashed).
        scoring: this benchmark's scoring-rule name (hashed) — the metric's identity.
        mean: the benchmark-level reduction over per-Case scores.
        selection_sha: the fingerprint of the case selection (hashed).
        focus: the short editorial line the leaderboard shows in its "Focus" column. It has
            to separate this benchmark from its siblings at a glance, since they share a dataset.
        dataset_url: where a reader can go and look at the source data.

    Returns:
        ``(benchmark, benchmark)`` — the ``Benchmark`` for the runtime's private routes, and the
        public ``Benchmark`` the registry publishes. The benchmark module exports both: the
        runtime needs the first, the catalogue the second.
    """

    revision = variant_revision(
        protocol_revision=protocol_revision,
        selection_sha=selection_sha,
        scoring=scoring,
    )
    variant = HealthbenchVariant(
        id=id,
        case_ids=case_ids,
        revision=revision,
        routes=Routes.for_variant(id, revision),
        mean=mean,
    )

    def build(case_count: int) -> Node:
        return build_variant_protocol(variant.routes, case_count, len(case_ids))

    def install(node: Url4Node, assets: Path) -> None:
        # Lazy import keeps the resource-only control-plane path from loading filesystem
        # runtime code (draco precedent).
        from screamingface_engine.benchmarks.healthbench.runtime import install as install_runtime

        # INVARIANT: every benchmark reads the SAME prepared asset directory — one immutable
        # answer key, selected from at serve time, never a per-benchmark prepare.
        install_runtime(node, assets / ASSET_BUNDLE_ID, variant)

    benchmark = Benchmark(
        id=id,
        title=title,
        description=description,
        revision=revision,
        case_count=len(case_ids),
        # INVARIANT: the declared policy matches the code — every benchmark reduces through
        # the shared finalize_candidate_result, which scores exactly the gradeable subset
        # and publishes coverage (coverage_declare). Declare `withhold` only if the
        # aggregate actually withholds (OME-1039).
        declaration=BenchmarkDeclaration(
            failure_policy="coverage_declare",
            interaction="single_shot",
            difficulty=difficulty,
        ),
        build=build,
        install=install,
        # FEATURE: benchmark descriptions on the leaderboard (OME-904). This definition is the
        # only place the benchmark's text is written; it is seeded from the catalogue at deploy.
        focus=focus,
        dataset_url=dataset_url,
        # Benchmark Provenance, baselines, notebook (OME-1455): threaded through verbatim,
        # the same pass-through as focus/dataset_url; shapes checked by `Benchmark` itself.
        **provenance,
        # WHY no Draft Feedback offer (owner decision 2026-10-07, OME-1513): the offer is a
        # per-Benchmark owner call, and today only IFEval carries one. The check-surface route
        # is still served (a paid Judge call over the Case's rubric) but is not advertised, so
        # the SDK refuses a Corrective Loop on this Benchmark before any money is spent.
        check_surface=None,
    )
    return variant, benchmark


def _model_route(model: str) -> str:
    return "/" + model.removeprefix("/")


__all__ = [
    "HealthbenchVariant",
    "VariantMean",
    "Routes",
    "build_variant_protocol",
    "case_ids_sha",
    "variant_revision",
    "healthbench_benchmark",
]
