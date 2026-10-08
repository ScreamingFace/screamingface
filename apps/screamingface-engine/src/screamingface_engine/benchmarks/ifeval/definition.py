"""Canonical IFEval as one Engine-owned, deterministic Benchmark."""

from __future__ import annotations

import hashlib
from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    DraftFeedbackOffer,
    candidate,
)
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    early_result,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.provenance import FrontierScore, NotPublished
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Url4Node

BENCHMARK_ID = "ifeval"
ASSET_BUNDLE_ID = BENCHMARK_ID
CASE_COUNT = 541
DATASET = "google/IFEval"
DATASET_REVISION = "966cd89545d6b6acfd7638bc708b98261ca58e84"
# The pip-installable, bug-fixed fork that inspect_evals pins — vendored under ./vendor.
VERIFIER_REPOSITORY = "josejg/instruction_following_eval"
VERIFIER_REVISION = "0c495b2f95155e8b10acb919ae283bfb4d5be6e2"
# OME-932: additive grade transport preserves the exam and its leaderboard identity.
# Official case keys and the pinned prompt correction remain unchanged.
PROTOCOL_REVISION = "ifeval-official-identity-v2"
CANDIDATE_WEB_SEARCH = False

# The verifier code is the grading contract, so changing it changes the Benchmark revision.
REVISION = hashlib.sha256(
    "\n".join(
        (
            DATASET,
            DATASET_REVISION,
            VERIFIER_REPOSITORY,
            VERIFIER_REVISION,
            PROTOCOL_REVISION,
            EVALUATION_PROTOCOL_REVISION,
            CANDIDATE_RESULT_SCHEMA,
            f"candidate_web_search={CANDIDATE_WEB_SEARCH}",
        )
    ).encode()
).hexdigest()[:16]

ROUTE_PREFIX = f"/benchmarks/{BENCHMARK_ID}/{REVISION}"
CASES_ROUTE = f"{ROUTE_PREFIX}/cases"
CHECK_ROUTE = f"{ROUTE_PREFIX}/check"
# The advertised check-surface port (OME-796): input-addressed because a black-box
# $candidate only ever sees $input — the adapter resolves the case behind the route.
DRAFT_FEEDBACK_ROUTE = f"{ROUTE_PREFIX}/check-surface"
CASE_GRADE_ROUTE = f"{ROUTE_PREFIX}/case-evaluation"
AGGREGATE_ROUTE = f"{ROUTE_PREFIX}/aggregate"
CASE_RESULT_ROUTE = f"{AGGREGATE_ROUTE}/case-result"


def _build(case_count: int) -> Node:
    """Build the canonical one-invocation IFEval expression.

    One Candidate answer per case, graded once — the protocol of Zhou et al.
    (arXiv:2311.07911), so scores compare directly to published IFEval results.
    """

    candidate_invocation = candidate(
        "$item.input",
        case_id="$item.id",
        case_index="$index",
        case_count=str(case_count),
        web_search=CANDIDATE_WEB_SEARCH,
    )
    checked_call = RelExpr(
        path=CHECK_ROUTE,
        context="$candidate_invocation",
        intent=Text("$item.case_id"),
    )
    checked = expr(
        src(checked_call, name="record", weight=0.0),
        src(
            RelExpr(
                path=CASE_GRADE_ROUTE,
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
        case_evaluation=early_result(
            preserve_candidate_outcome(
                candidate_invocation=candidate_invocation,
                grading=checked,
                case_id="$item.id",
            ),
            aggregate_route=AGGREGATE_ROUTE,
            selected_case_count=case_count,
        ),
        selected_case_count=case_count,
        available_case_count=CASE_COUNT,
        aggregate_route=AGGREGATE_ROUTE + "/graded",
    )


def install_ifeval(node: Url4Node, assets: Path) -> None:
    """Install the IFEval cases, verifier, and reducers."""

    # Lazy import keeps the resource-only control plane from loading verifier runtime deps.
    from screamingface_engine.benchmarks.ifeval.runtime import install

    install(node, assets / ASSET_BUNDLE_ID)


IFEVAL = Benchmark(
    id=BENCHMARK_ID,
    title="IFEval",
    description=(
        "The canonical 541-prompt instruction-following benchmark "
        "(https://arxiv.org/abs/2311.07911), graded by deterministic strict and loose "
        "verification. Each Case invokes the Candidate exactly once. Case ids are the "
        "official IFEval keys; one pinned-dataset row (key 2785) is patched to the "
        "official harness prompt, whose text matches its graded constraints."
    ),
    focus="Instruction following",
    # WHY no dataset_url: the IFEval dataset is vendored inside this Engine
    # (screamingface_engine.benchmarks.ifeval.vendor), so no single public URL is authoritative.
    revision=REVISION,
    case_count=CASE_COUNT,
    # INVARIANT: the declared policy matches the code — this benchmark reduces through the
    # shared finalize_candidate_result, which scores exactly the gradeable subset and
    # publishes coverage (coverage_declare). Declare `withhold` only if the aggregate
    # actually withholds (OME-1039).
    declaration=BenchmarkDeclaration(
        failure_policy="coverage_declare",
        interaction="single_shot",
        # Instruction following still trips strong models on strict verification, but the
        # material itself is everyday prose, not expert work (OME-1257).
        difficulty="medium",
    ),
    build=_build,
    install=install_ifeval,
    # WHY IFEval is the ONE Benchmark that offers Draft Feedback (owner decision 2026-10-07,
    # OME-1513): the published Corrective-Loop work targets IFEval, and its verifier is
    # deterministic checker code, so a mid-run check is free and leaks only pass/fail per
    # instruction. Every other Benchmark, imported or hand-built, has the offer off until the
    # owner turns it on by name — never by grading family.
    check_surface=DraftFeedbackOffer(
        check_route=DRAFT_FEEDBACK_ROUTE,
        feedback_intent="feedback",
        expected_check_cost="free",
    ),
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2311.07911",
    authors="Zhou et al., 2023",
    citation=(
        "@misc{zhou2023instructionfollowingevaluationlargelanguage,\n"
        "      title={Instruction-Following Evaluation for Large Language Models}, \n"
        "      author={Jeffrey Zhou and Tianjian Lu and Swaroop Mishra and Siddhartha"
        " Brahma and Sujoy Basu and Yi Luan and Denny Zhou and Le Hou},\n"
        "      year={2023},\n"
        "      eprint={2311.07911},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.CL},\n"
        "      url={https://arxiv.org/abs/2311.07911}, \n"
        "}"
    ),
    harness_url=(
        "https://github.com/josejg/instruction_following_eval/tree/0c495b2f95155e8b10acb919ae283bfb4d5be6e2"
    ),
    license="Apache-2.0",
    license_note=(
        "google/IFEval dataset card; the vendored verifier (the bug-fixed fork inspect_evals "
        "pins) is Apache-2.0."
    ),
    human_baseline=NotPublished(reason="the IFEval paper reports no human study"),
    # Frontier score: IFEval accuracy (variant not stated in the source.
    frontier_score=FrontierScore(
        score=0.948,
        model="GPT-5.2",
        source_url="https://huggingface.co/Qwen/Qwen3.5-397B-A17B",
        as_of="2026-02",
    ),
    notebook="07_ifeval",
)

__all__ = ["ASSET_BUNDLE_ID", "IFEVAL", "install_ifeval"]
