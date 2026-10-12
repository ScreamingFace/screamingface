"""How any GDPval benchmark is built — identity, addresses, and the one expression tree.

The template is fixed: one dataset, one prepared answer key, one judge, one grading chain. A
benchmark varies only which Cases it serves, how it totals them, and what it calls itself — and
``id`` decides every route address.

``variant_revision`` fingerprints the whole identity into 16 hex characters; ``Routes`` hangs the
six protocol routes plus the draft-feedback offer under ``/benchmarks/<id>/<revision>/``;
``build_variant_protocol`` writes the url4 tree. ``gdpval_benchmark`` is the one call a benchmark
makes.

INVARIANT: a benchmark's revision changes if ANY hashed input changes — dataset pin, preparer,
container filter, judge pinning, grader template, selection, scoring rule. An expression
addressed to an old revision physically cannot resolve against a new benchmark.

WHY this mirrors ``healthbench/variant.py`` rather than importing it: that module's tree is bound to
simple-evals parity and its worst30 benchmark's revision is FROZEN at a published value.
Parameterising it to serve a second benchmark would put a live, frozen identity at risk for the sake
of removing a structural resemblance. The two trees agree today because the rubric shapes agree, not
because they answer to the same authority.
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
from screamingface_engine.benchmarks.gdpval import verdict
from screamingface_engine.benchmarks.gdpval.prompts import GRADER_TEMPLATE
from screamingface_engine.benchmarks.gdpval.revision_inputs import (
    DATASET,
    DATASET_REVISION,
    JUDGE_MODEL,
    JUDGE_PARAMS,
    JUDGE_RETRIES,
    PREPARER_REVISION,
)
from screamingface_engine.benchmarks.gdpval.rubric_filter import FILTER_REVISION
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    early_result,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.provenance import ProvenanceFields
from url4 import Node, RelExpr, Text, expr, iterate, render, src, struct
from url4.peer.server import Url4Node

#: The one physical asset directory every GDPval benchmark reads — one immutable prepare.
ASSET_BUNDLE_ID = "gdpval"

#: The pass criterion of the mid-run draft-feedback offer.
CHECK_CRITERION = "gdpval-pass.v1"

VariantMean = Callable[[Sequence[float | None]], float | None]


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
class GdpvalVariant:
    """One GDPval identity: which Cases, which final mean, at which addresses."""

    id: str
    case_ids: tuple[int, ...]
    revision: str
    routes: Routes
    mean: VariantMean


def variant_revision(*, protocol_revision: str, selection_sha: str, scoring: str) -> str:
    """Fingerprint one benchmark identity into the 16 hex characters its routes carry.

    Everything a Candidate's score depends on goes in — including ``FILTER_REVISION``, because
    which criteria are scored is as much a part of this benchmark as which Cases are asked.
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
                FILTER_REVISION,
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

    Reading outside-in, the Engine will:

    1. Fetch the Cases — a work request plus its flattened reference text — from
       ``routes.cases``, and for each:
    2. Ask the Candidate to do the work, then fetch that Case's surviving rubric criteria from
       ``routes.tasks`` — one judge request per criterion, each carrying the Candidate's answer
       already rendered into a grader prompt.
    3. Send each grader prompt to the judge as a single user message and parse its yes/no verdict
       via ``routes.verdict``. A malformed reply raises, so ``;retry=`` re-resolves the NESTED
       judge call, and that retry opts out of the gateway cache (OME-1533) so it gets a fresh
       sample, not the stored malformed reply. That nesting is the point: as a sibling, a
       malformed-but-successful model call would never be retried.
    4. Roll up: criterion rows → ``routes.rubric_evaluation`` → per-Case score at
       ``routes.case_evaluation`` → every Case row into ``routes.aggregate``.

    AIDEV-NOTE: stage 3 is where this benchmark's cost lives. One judge call per criterion over 102
    Cases is ~4,498 calls per candidate. That is deliberate — judging a criterion in isolation
    stops a long rubric crowding out its own tail — but it is the number to check before
    scheduling a full run.
    """

    candidate_invocation = candidate(
        "$item.input",
        case_id="$item.id",
        case_index="$index",
        case_count=str(case_count),
        web_search=False,
    )
    # Stage 3a — one pre-rendered grader prompt to the judge.
    # INVARIANT: the judge call's intent is EMPTY (`!''`). A non-empty intent becomes a SYSTEM
    # message; the whole grader prompt is meant to arrive as one user message.
    judge_reply = RelExpr(
        path=_model_route(JUDGE_MODEL),
        context="$item.grader_prompt",
        intent=Text(""),
        params=JUDGE_PARAMS,
    )
    # Stage 3b — one graded criterion: judge reply → parsed verdict → stored row.
    rubric_evaluation = expr(
        src("$item.case_record", name="case_record", weight=0.0),
        src("$item.rubric_record", name="rubric_record", weight=0.0),
        verdict.call(
            judge_reply,
            case_id="$item.case_id",
            rubric_id="$item.rubric_id",
            route=routes.verdict,
            retry=JUDGE_RETRIES,
        ),
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
    # Stage 2 — per Case: call the Candidate once, fan out one judge request per criterion.
    rubric_items = iterate(
        RelExpr(
            path=routes.judge_requests,
            context="$candidate_invocation",
            intent=Text("$item.case_id"),
        ),
        body=(src(rubric_evaluation, name="evaluated", weight=0.0),),
        intent=Text("$evaluated"),
    )
    # Stage 4a — roll a Case's criterion rows up into one per-Case score.
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


def gdpval_benchmark(
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
) -> tuple[GdpvalVariant, Benchmark]:
    """Wire one GDPval benchmark: identity → addresses → expression → private routes."""

    revision = variant_revision(
        protocol_revision=protocol_revision,
        selection_sha=selection_sha,
        scoring=scoring,
    )
    variant = GdpvalVariant(
        id=id,
        case_ids=case_ids,
        revision=revision,
        routes=Routes.for_variant(id, revision),
        mean=mean,
    )

    def build(case_count: int) -> Node:
        return build_variant_protocol(variant.routes, case_count, len(case_ids))

    def install(node: Url4Node, assets: Path) -> None:
        # Lazy import keeps the resource-only control-plane path from loading filesystem runtime
        # code (draco precedent).
        from screamingface_engine.benchmarks.gdpval.runtime import install as install_runtime

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
    "ASSET_BUNDLE_ID",
    "CHECK_CRITERION",
    "GdpvalVariant",
    "VariantMean",
    "Routes",
    "build_variant_protocol",
    "case_ids_sha",
    "variant_revision",
    "gdpval_benchmark",
]
