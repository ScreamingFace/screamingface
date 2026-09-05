"""MedXpertQA (Text) as one Engine-owned, judge-free Benchmark.

FEATURE: expert-level medical multiple choice — 2,450 questions, one letter each, graded by
string comparison. The first board whose grading spends NO judge tokens.

INVARIANT — the exchange is TWO candidate invocations. Turn 1 reasons freely; turn 2 sends only
the trigger, so the model completes "…the answer is ___" and its commitment comes FIRST. That
message layout, not any instruction, is what makes the official first-match extraction correct.
A one-shot prompt with the trigger appended produces letter-LAST essays that the same parser
misreads: measured at 35.5% against a true 70.2%.

NAMED DEVIATION — the two-turn exchange is imposed at the CANDIDATE BOUNDARY. The Engine invokes
`$candidate` as an opaque recipe (`ensemble/policy.py`: the client compiles the whole candidate
expression, the Engine "contributes generic invocation"), so a board cannot reach inside a
Fusion. For a solo model this reproduces the official protocol exactly. For a Fusion it does not:
a per-member implementation runs two-turn inside each member and shows the synthesiser their full
analyses, which is not expressible here. Fusion numbers from this board are therefore not
comparable to a per-member implementation, and the description says so.

References:
    - Paper: https://arxiv.org/abs/2501.18362
    - Dataset: https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA
    - Official harness: https://github.com/TsinghuaC3I/MedXpertQA (eval/)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    CheckSurface,
    candidate,
)
from screamingface_engine.benchmarks.medxpert.pins import (
    DATASET,
    DATASET_CONFIG,
    DATASET_REVISION,
    DATASET_SPLIT,
    PREPARER_REVISION,
    PROTOCOL_REVISION,
)
from screamingface_engine.benchmarks.medxpert.prompts import (
    COT_PROMPT_TEMPLATE,
    COT_TRIGGER_TEMPLATE,
)
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    preserve_candidate_outcome,
)
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Url4Node

BENCHMARK_ID = "medxpert"
ASSET_BUNDLE_ID = BENCHMARK_ID
CASE_COUNT = 2450
DATASET_URL = "https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA"
# INVARIANT: grading is retrieval-free — the answer key is a fixed letter, and a model that
# searched would be answering a different question from the one the leaderboard asks.
CANDIDATE_WEB_SEARCH = False


def compute_revision(
    *,
    dataset_revision: str = DATASET_REVISION,
    cot_template: str = COT_PROMPT_TEMPLATE,
    trigger_template: str = COT_TRIGGER_TEMPLATE,
) -> str:
    """Fingerprint this exam into the 16 hex characters its routes carry.

    WHY the prompt templates are hashed: this board has no judge, so the prompt is the only thing
    between a model and its score. A changed template is a changed exam and must re-address every
    route — otherwise already-recorded submissions would silently become incomparable.
    """

    return hashlib.sha256(
        "\n".join(
            (
                DATASET,
                DATASET_CONFIG,
                DATASET_SPLIT,
                dataset_revision,
                PREPARER_REVISION,
                PROTOCOL_REVISION,
                EVALUATION_PROTOCOL_REVISION,
                CANDIDATE_RESULT_SCHEMA,
                cot_template,
                trigger_template,
            )
        ).encode()
    ).hexdigest()[:16]


REVISION = compute_revision()

ROUTE_PREFIX = f"/benchmarks/{BENCHMARK_ID}/{REVISION}"
CASES_ROUTE = f"{ROUTE_PREFIX}/cases"
CHECK_ROUTE = f"{ROUTE_PREFIX}/check"
CHECK_SURFACE_ROUTE = f"{ROUTE_PREFIX}/check-surface"
CASE_EVALUATION_ROUTE = f"{ROUTE_PREFIX}/case-evaluation"
AGGREGATE_ROUTE = f"{ROUTE_PREFIX}/aggregate"


def _build(case_count: int) -> Node:
    """Build the two-turn MedXpertQA expression.

    Reading outside-in: fetch the Cases, and for each ask the Candidate to reason, then ask the
    SAME Candidate to commit against the bare trigger, then check the committed letter against
    the private key and roll the rows into the aggregate.
    """

    # Turn 1 — free reasoning. The cases file bakes the ready-made CoT prompt.
    reasoning = candidate("$item.cot_prompt", web_search=CANDIDATE_WEB_SEARCH, binding="$candidate")
    # Turn 2 — the commit. Its input carries the question and turn 1's reasoning, and ends on the
    # trigger; the model finishes that sentence, so the letter leads.
    commit = candidate(
        render(
            struct(
                {
                    "question": "$item.input",
                    "reasoning": "$reasoning",
                    "trigger": "$item.trigger",
                }
            )
        ),
        web_search=CANDIDATE_WEB_SEARCH,
        binding="$candidate",
    )
    checked = expr(
        src(reasoning, name="reasoning", weight=0.0),
        src(
            RelExpr(
                path=CHECK_ROUTE,
                # D8: the shared candidate envelope has no field for auxiliary text, so the
                # reasoning reaches the report through THIS board's own check envelope.
                context=render(
                    struct({"reasoning": "$reasoning", "commit": "$candidate_invocation"})
                ),
                intent=Text("$item.case_id"),
            ),
            name="record",
            weight=0.0,
        ),
        src(
            RelExpr(
                path=CASE_EVALUATION_ROUTE,
                context=render(struct({"attempt_1": "$record"})),
                intent=Text("$item.case_id"),
            ),
            name="case_evaluation",
            weight=0.0,
        ),
        intent=Text("$case_evaluation"),
    )
    return build_evaluation_protocol(
        cases_route=CASES_ROUTE,
        case_evaluation=preserve_candidate_outcome(
            # The COMMIT is the candidate outcome — it holds the answer being graded.
            candidate_invocation=commit,
            grading=checked,
            case_id="$item.id",
        ),
        selected_case_count=case_count,
        available_case_count=CASE_COUNT,
        aggregate_route=AGGREGATE_ROUTE,
    )


def install_medxpert(node: Url4Node, assets: Path) -> None:
    """Install the MedXpertQA cases, checker and reducers."""

    from screamingface_engine.benchmarks.medxpert.runtime import install

    install(node, assets / ASSET_BUNDLE_ID)


MEDXPERT = Benchmark(
    id=BENCHMARK_ID,
    title="MedXpertQA",
    description=(
        "2,450 expert-level medical multiple-choice questions (MedXpertQA Text). The model "
        "reasons step by step, then commits to one lettered choice; grading is an exact match "
        "against the published key, so no judge tokens are spent. Benchmark score = plain "
        "accuracy over the cases run, reported beside the fraction actually answered — a model "
        "that returns nothing on some rows is scored over fewer of them. "
        "The two-turn exchange is applied at the candidate boundary, which reproduces the "
        "official protocol for a single model; for a fusion the exchange wraps the whole "
        "ensemble rather than each member, so those numbers are not comparable to a per-member "
        "implementation."
    ),
    revision=REVISION,
    case_count=CASE_COUNT,
    build=_build,
    install=install_medxpert,
    focus="Expert medical multiple choice",
    dataset_url=DATASET_URL,
    declaration=BenchmarkDeclaration(
        # WHY "coverage_declare" and NOT "withhold": this axis governs a Case that never got a
        # valid grade, and those are infrastructure failures, which this board hands to the
        # shared `finalize_candidate_result` — it scores the gradeable subset and publishes
        # coverage. An empty ANSWER is a different thing: it does get a grade, of 0.0, per the
        # official empty-prediction verdict. That behaviour lives in `aggregate._scored`, not
        # here, and declaring `withhold` for it would misdescribe what the reducer does.
        failure_policy="coverage_declare",
        # WHY "multi_turn": the board invokes the Candidate twice per Case — reason, then commit.
        # Declared because it doubles the invocation cost and changes what a Fusion entrant is
        # asked to do (the exchange wraps the ensemble, not each member).
        interaction="multi_turn",
    ),
    check_surface=CheckSurface(
        check_route=CHECK_SURFACE_ROUTE,
        feedback_intent="feedback",
        # WHY free: grading is pure string comparison. Declaring it paid would be a lie the SDK
        # repeats to the user before every run.
        expected_check_cost="free",
    ),
)

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASES_ROUTE",
    "CASE_COUNT",
    "CASE_EVALUATION_ROUTE",
    "CHECK_ROUTE",
    "CHECK_SURFACE_ROUTE",
    "MEDXPERT",
    "REVISION",
    "compute_revision",
    "install_medxpert",
]
