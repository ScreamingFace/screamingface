"""How ANY DRACO board is built — identity, addresses, and the one expression tree.

Think of it as printing an exam paper from a template. The template is fixed: the same
100-case dataset (``perplexity-ai/draco``), the same criteria, the same Judge
(Gemini-3.1-Pro Preview), the same grading chain. What the printer varies per board is
exactly two things:

    how many times the Judge grades each criterion   (``judge_passes``)
    what it calls itself                             (``id`` — which decides every route address)

Everything else is derived. ``draco_revision`` fingerprints the whole board identity
into a 16-hex revision; ``Routes`` hangs the seven protocol routes plus the check
surface under ``/benchmarks/<id>/<revision>/``; ``build_draco_protocol`` writes the
url4 expression tree. ``draco_benchmark`` is the one call a board module makes.

INVARIANT: two boards built here share the baked assets and differ ONLY where the
knobs above differ. A board's revision changes if ANY hashed input changes, so an
expression addressed to an old revision physically cannot resolve against a new exam.

INVARIANT (frozen canonical): the canonical board keeps the pre-factory revision —
``draco_revision`` reproduces the original hash tuple byte-for-byte, so ``draco``'s
routes, scoreboard seeds, and every published submission stay exactly where they are.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import Benchmark, CheckSurface, candidate
from screamingface_engine.benchmarks.draco.prompts import JUDGE_INSTRUCTIONS
from screamingface_engine.benchmarks.draco.verdict import call as criterion_verdict
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    preserve_candidate_outcome,
)
from url4 import Node, RelExpr, Text, expr, iterate, render, src, struct
from url4.peer.server import Url4Node

# --- the shared pins: the dataset, the judge, and the retrieval policy ----------------

DATASET = "perplexity-ai/draco"
DATASET_REVISION = "ce076749809027649ebd331bcb70f42bf720d387"
DATASET_PREPARER_REVISION = "datasets-5.0.0"
CASE_COUNT = 100
# The one physical asset directory every DRACO board reads — one immutable case/rubric
# bake, never a per-board one. The deployment names this id when it prepares the bundle
# (OME-875); definition.py re-exports it for the image build.
ASSET_BUNDLE_ID = "draco"
# The paper pins Gemini-3-Pro Preview, which Google shut down on 2026-03-09. Google designated
# Gemini-3.1-Pro Preview as its replacement, so this reproduction uses that successor model.
JUDGE_MODEL = "openrouter/google/gemini-3.1-pro-preview"
RETRIEVAL_POLICY_ID = "draco/reproduction"
EXCLUDED_DOMAINS = (
    "arxiv.org",
    "huggingface.co",
    "openrouter.ai",
    "paperswithcode.com",
    "alphaxiv.org",
    "semanticscholar.org",
    "research.perplexity.ai",
)
JUDGE_PARAMS = (
    # The same model is also a DRACO Candidate. Its route can retrieve, but Grading cannot. The
    # Runner consumes this control and sends no search field or tools to AI Gateway, so the Judge
    # request remains eligible for the exact-response cache.
    ("web_search", "false"),
    ("temperature", "0.2"),
    # The official low-reasoning setting is added once AI Gateway exposes a validated
    # OpenRouter parameter for it. Unknown fields fail closed, so guessing here breaks every
    # judge call rather than producing a documented protocol deviation.
    ("max_tokens", "4096"),
)
# The pass criterion of the mid-run check surface (OME-829/830). Declared here rather
# than imported from check_policy, which reads this module for the judge pinning.
CHECK_CRITERION = "draco-pass.v1"


@dataclass(frozen=True, slots=True)
class Routes:
    """The seven addresses one board answers on, all under its own revision prefix."""

    prefix: str
    cases: str
    tasks: str
    verdict: str
    criterion_evaluation: str
    case_evaluation: str
    aggregate: str
    check_surface: str

    @classmethod
    def for_exam(cls, benchmark_id: str, revision: str) -> Routes:
        prefix = f"/benchmarks/{benchmark_id}/{revision}"
        return cls(
            prefix=prefix,
            cases=f"{prefix}/cases",
            tasks=f"{prefix}/tasks",
            verdict=f"{prefix}/criterion-verdict",
            criterion_evaluation=f"{prefix}/criterion-evaluation",
            case_evaluation=f"{prefix}/case-evaluation",
            aggregate=f"{prefix}/aggregate",
            check_surface=f"{prefix}/check-surface/{CHECK_CRITERION}",
        )


@dataclass(frozen=True, slots=True)
class DracoExam:
    """One DRACO board identity: how many judge passes, at which addresses.

    This is what the runtime needs to serve a board — it carries no metadata a human
    reads (that lives on the ``Benchmark``), only what the protocol handlers consume.
    """

    id: str
    revision: str
    routes: Routes
    judge_passes: int


def draco_revision(*, protocol_revision: str, judge_passes: int) -> str:
    """Fingerprint one board identity into the 16 hex characters its routes carry.

    Everything a Candidate's score depends on goes in: the dataset pin, the preparer
    that turned it into assets, the shared evaluation protocol, the Candidate result
    schema, the retrieval policy, the judge pinning, the judge-instruction bytes — plus
    the two per-board inputs (protocol revision and pass count, which also decides the
    pass seeds). Change any of them and every route address moves, which is the only
    safe way to change an exam.

    INVARIANT (frozen): the tuple below reproduces the original canonical hash
    byte-for-byte — same order, same repr() shapes — so the canonical board's revision
    survives the factory refactor untouched (pinned by test_draco_3pass_definition.py).
    """

    judge_seeds = tuple(range(1, judge_passes + 1))
    return hashlib.sha256(
        "\n".join(
            (
                DATASET,
                DATASET_REVISION,
                DATASET_PREPARER_REVISION,
                protocol_revision,
                EVALUATION_PROTOCOL_REVISION,
                CANDIDATE_RESULT_SCHEMA,
                RETRIEVAL_POLICY_ID,
                repr(EXCLUDED_DOMAINS),
                JUDGE_MODEL,
                str(judge_passes),
                repr(judge_seeds),
                repr(JUDGE_PARAMS),
                JUDGE_INSTRUCTIONS,
            )
        ).encode()
    ).hexdigest()[:16]


def build_draco_protocol(routes: Routes, case_count: int, judge_passes: int) -> Node:
    """Build the whole benchmark as one url4 expression tree (a recipe, not a run).

    The shape is canonical DRACO's: one Candidate invocation per Case, then one Judge
    call per criterion per pass — ``judge_passes`` verdicts per criterion, each on its
    own stable seed so the passes occupy independent cache slots (a run can never
    collapse them into one cached response). The criterion evaluation folds the
    ``judge_passes`` evidence records into one Engine-bound record, the case evaluation
    rolls criteria up, and the aggregate reduces every Case row into the Candidate
    Result.

    ``case_count`` < ``CASE_COUNT`` slices to a partial run (the SDK's ``limit=N``);
    equality means the full set. Every route is revision-pinned.
    """

    candidate_invocation = candidate(
        "$item.input",
        web_search=True,
        web_search_exclude=EXCLUDED_DOMAINS,
    )
    judge_calls = tuple(
        src(
            criterion_verdict(
                RelExpr(
                    path=_model_route(JUDGE_MODEL),
                    # Every dynamic value is local to this iteration item. The model sees only
                    # the official prompt fields; the Engine binds the known criterion id after
                    # the reply, so grading never trusts a model-generated identifier.
                    context=_judge_context(),
                    intent=Text(_url4_text(JUDGE_INSTRUCTIONS)),
                    # Stable pass seeds create independent cache slots. Repeated benchmark
                    # runs may reuse those slots, but one run can never collapse judge
                    # passes into one cached response.
                    params=(*JUDGE_PARAMS, ("seed", str(run))),
                ),
                "$item.criterion_id",
                case_id="$item.case_id",
                sequence=run,
                route=routes.verdict,
            ),
            name=f"verdict_{run}",
            weight=0.0,
        )
        for run in range(1, judge_passes + 1)
    )
    criterion_evaluation = expr(
        src("$item.case_record", name="case_record", weight=0.0),
        src("$item.check_record", name="check_record", weight=0.0),
        *judge_calls,
        src(
            RelExpr(
                path=routes.criterion_evaluation,
                context=render(
                    struct(
                        {
                            "case": "$case_record",
                            "check": "$check_record",
                            **{
                                f"evidence_{run}": f"$verdict_{run}"
                                for run in range(1, judge_passes + 1)
                            },
                        }
                    )
                ),
                intent=Text("$item.case_id"),
            ),
            name="criterion_evaluation",
            weight=0.0,
        ),
        intent=Text("$criterion_evaluation"),
    )
    criteria = iterate(
        RelExpr(
            path=routes.tasks,
            # This collection boundary invokes the Candidate exactly once, then returns the
            # criterion tasks plus Engine-bound Case/Check records for lossless aggregation.
            context="$candidate_invocation",
            intent=Text("$item.case_id"),
        ),
        body=(src(criterion_evaluation, name="evaluated", weight=0.0),),
        intent=Text("$evaluated"),
    )
    case_evaluation = expr(
        src(criteria, name="criteria", weight=0.0),
        src(
            RelExpr(
                path=routes.case_evaluation,
                context="$criteria",
                intent=Text("$item.case_id"),
            ),
            name="case_evaluation",
            weight=0.0,
        ),
        intent=Text("$case_evaluation"),
    )
    return build_evaluation_protocol(
        cases_route=routes.cases,
        case_evaluation=preserve_candidate_outcome(
            candidate_invocation=candidate_invocation,
            grading=case_evaluation,
            case_id="$item.id",
        ),
        selected_case_count=case_count,
        available_case_count=CASE_COUNT,
        aggregate_route=routes.aggregate,
    )


def draco_benchmark(
    *,
    id: str,
    title: str,
    description: str,
    judge_passes: int,
    protocol_revision: str,
    focus: str | None = None,
    dataset_url: str | None = None,
) -> tuple[DracoExam, Benchmark]:
    """Wire one DRACO board: identity → addresses → expression → private routes.

    Args:
        id: the public benchmark id; it becomes the first path segment of every route.
        title: the human name shown in the catalogue.
        description: the catalogue description — it must say how many judge passes this
            board runs, because that is the difference a reader cannot see anywhere else.
        judge_passes: how many times the Judge grades each answer (the pass seeds
            derive from it).
        protocol_revision: this board's own protocol version string (hashed).
        focus: the short editorial line the leaderboard shows in its "Focus" column. It has
            to separate this board from its siblings at a glance, since they share a dataset.
        dataset_url: where a reader can go and look at the source data.

    Returns:
        ``(exam, benchmark)`` — the ``DracoExam`` for the runtime's private routes, and
        the public ``Benchmark`` the registry publishes. The board module exports both:
        the runtime needs the first, the catalogue the second.
    """

    revision = draco_revision(
        protocol_revision=protocol_revision,
        judge_passes=judge_passes,
    )
    exam = DracoExam(
        id=id,
        revision=revision,
        routes=Routes.for_exam(id, revision),
        judge_passes=judge_passes,
    )

    def build(selected_case_count: int) -> Node:
        return build_draco_protocol(exam.routes, selected_case_count, exam.judge_passes)

    def install(node: Url4Node, assets: Path) -> None:
        # Lazy import keeps the resource-only control-plane path from loading filesystem
        # runtime code (healthbench precedent).
        from screamingface_engine.benchmarks.draco.runtime import install as install_runtime

        # INVARIANT: every board reads the SAME baked asset directory — one immutable
        # case/rubric set, never a per-board bake.
        install_runtime(node, assets / ASSET_BUNDLE_ID, exam)

    benchmark = Benchmark(
        id=id,
        title=title,
        description=description,
        revision=revision,
        case_count=CASE_COUNT,
        build=build,
        install=install,
        aggregate_route=exam.routes.aggregate,
        # FEATURE: benchmark descriptions on the leaderboard (OME-904). This definition is the
        # only place the board's text is written; it is seeded from the catalogue at deploy.
        focus=focus,
        dataset_url=dataset_url,
        # The mid-run check is a real Judge call over the case rubric, so a corrective
        # loop's check budget is paid (same surface as canonical).
        check_surface=CheckSurface(
            check_route=exam.routes.check_surface,
            feedback_intent="feedback",
            expected_check_cost="paid",
        ),
    )
    return exam, benchmark


def _model_route(model: str) -> str:
    return "/" + model.removeprefix("/")


def _judge_context() -> str:
    # The U+2028 LINE SEPARATOR between fields is part of the request payload — and
    # therefore of the judge cache key. It must stay byte-identical to the original
    # canonical prompt or the archived draco-cache-seed rows would never match.
    return "\u2028".join(
        (
            "<criterion_type>",
            "$item.criterion_type",
            "</criterion_type>",
            "<criterion>",
            "$item.criterion",
            "</criterion>",
            "<query>",
            "$item.question",
            "</query>",
            "<response>",
            "$item.answer",
            "</response>",
        )
    )


def _url4_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", "\u2028").replace("\t", " ")
    unsupported = next(
        (character for character in normalized if character < " " or character == "\x7f"),
        None,
    )
    if unsupported is not None:
        raise ValueError(
            f"Benchmark prompt contains unsupported control character U+{ord(unsupported):04X}"
        )
    return normalized.replace("$", "$$")


__all__ = [
    "ASSET_BUNDLE_ID",
    "CASE_COUNT",
    "CHECK_CRITERION",
    "DATASET",
    "DATASET_PREPARER_REVISION",
    "DATASET_REVISION",
    "DracoExam",
    "EXCLUDED_DOMAINS",
    "JUDGE_MODEL",
    "JUDGE_PARAMS",
    "RETRIEVAL_POLICY_ID",
    "Routes",
    "build_draco_protocol",
    "draco_benchmark",
    "draco_revision",
]
