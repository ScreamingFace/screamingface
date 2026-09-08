"""ContractEval as one Engine-owned, judge-free Benchmark.

FEATURE: clause-level legal extraction over the CUAD test split — 4,182 (contract, clause
category) pairs. The model quotes the answering sentences verbatim or says "No related clause.",
and grading is pure string containment, so no judge tokens are spent.

INVARIANT — the headline score is F1 from a DATASET-level confusion matrix, not a mean of case
scores. 70.3% of rows have no clause, so a model that always abstains earns ~70% accuracy while
answering nothing; F1 scores it 0. That is why `aggregate` is the only reducer in this repo that
carries per-case polarity up to the scorer instead of averaging.

References:
    - Paper: https://arxiv.org/abs/2508.03080 · https://aclanthology.org/2025.nllp-1.19/
    - Reference harness: https://github.com/olivialiu121/ContractEval (MIT)
    - Dataset: https://huggingface.co/datasets/theatticusproject/cuad-qa
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.contracteval.pins import (
    DATASET,
    DATASET_REVISION,
    DATASET_SPLIT,
    PREPARER_REVISION,
    PROTOCOL_REVISION,
)
from screamingface_engine.benchmarks.contracteval.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    candidate,
)
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    preserve_candidate_outcome,
)
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Url4Node

BENCHMARK_ID = "contracteval"
ASSET_BUNDLE_ID = BENCHMARK_ID
CASE_COUNT = 4182
DATASET_URL = "https://huggingface.co/datasets/theatticusproject/cuad-qa"
# INVARIANT: grading is retrieval-free — the answer must be quoted FROM the supplied contract,
# and a model that searched the web would be answering a different question.
CANDIDATE_WEB_SEARCH = False


def compute_revision(
    *,
    dataset_revision: str = DATASET_REVISION,
    system_prompt: str = SYSTEM_PROMPT,
    user_template: str = USER_TEMPLATE,
) -> str:
    """Fingerprint this exam into the 16 hex characters its routes carry.

    WHY the prompts are hashed: this board has no judge, so the prompt is the only thing between
    a model and its score — and here it is unusually load-bearing, because "Do not rephrase or
    summarize" is what makes verbatim containment a fair test at all. A changed prompt is a
    changed exam and must re-address every route.
    """

    return hashlib.sha256(
        "\n".join(
            (
                DATASET,
                DATASET_SPLIT,
                dataset_revision,
                PREPARER_REVISION,
                PROTOCOL_REVISION,
                EVALUATION_PROTOCOL_REVISION,
                CANDIDATE_RESULT_SCHEMA,
                system_prompt,
                user_template,
            )
        ).encode()
    ).hexdigest()[:16]


REVISION = compute_revision()

ROUTE_PREFIX = f"/benchmarks/{BENCHMARK_ID}/{REVISION}"
CASES_ROUTE = f"{ROUTE_PREFIX}/cases"
CHECK_ROUTE = f"{ROUTE_PREFIX}/check"
CASE_EVALUATION_ROUTE = f"{ROUTE_PREFIX}/case-evaluation"
AGGREGATE_ROUTE = f"{ROUTE_PREFIX}/aggregate"


def _build(case_count: int) -> Node:
    """Build the single-shot ContractEval expression.

    One Candidate answer per Case, checked once. The whole instruction set is baked into
    `$item.input` by `prepare`, so there is nothing to assemble here.
    """

    candidate_invocation = candidate("$item.input", web_search=CANDIDATE_WEB_SEARCH)
    checked = expr(
        src(
            RelExpr(
                path=CHECK_ROUTE,
                context="$candidate_invocation",
                intent=Text("$item.case_id"),
            ),
            name="record",
            weight=0.0,
        ),
        src(
            RelExpr(
                path=CASE_EVALUATION_ROUTE,
                # WHY a struct and not the bare record: the case-evaluation route is the
                # object-shaped `attempt_records_endpoint`. The array-shaped sibling exists for
                # rubric `iterate` fan-outs and rejects this payload (OME-1126 live failure).
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
            candidate_invocation=candidate_invocation,
            grading=checked,
            case_id="$item.id",
        ),
        selected_case_count=case_count,
        available_case_count=CASE_COUNT,
        aggregate_route=AGGREGATE_ROUTE,
    )


def install_contracteval(node: Url4Node, assets: Path) -> None:
    """Install the ContractEval cases, checker and reducers."""

    # Lazy import keeps the resource-only control plane free of runtime deps.
    from screamingface_engine.benchmarks.contracteval.runtime import install

    install(node, assets / ASSET_BUNDLE_ID)


CONTRACTEVAL = Benchmark(
    id=BENCHMARK_ID,
    title="ContractEval",
    description=(
        "4,182 clause-extraction questions over 102 real commercial contracts (CUAD test "
        "split). The model is given a full contract and one of 41 clause categories, and must "
        'quote the answering sentences verbatim or reply "No related clause." Grading is '
        "deterministic string containment — every gold sentence must appear, with no partial "
        "credit — so no judge tokens are spent. Benchmark score = F1 over the whole run, "
        "reported beside precision, recall, F2, accuracy, the abstention rate and the "
        'false-abstention ("laziness") rate. F1 rather than accuracy is the headline because '
        "70% of rows have no clause, so a model that always abstains would otherwise look "
        "strong while answering nothing."
    ),
    revision=REVISION,
    case_count=CASE_COUNT,
    build=_build,
    install=install_contracteval,
    focus="Legal clause extraction",
    dataset_url=DATASET_URL,
    declaration=BenchmarkDeclaration(
        # WHY "coverage_declare": this axis governs a Case that never got a valid grade — an
        # infrastructure failure — which the shared `finalize_candidate_result` handles by
        # scoring the gradeable subset and publishing coverage. A model that answers WRONGLY
        # does get a grade, of 0.0, and stays in the confusion matrix.
        failure_policy="coverage_declare",
        # One Candidate invocation per Case.
        interaction="single_shot",
    ),
    # AIDEV-NOTE: no check_surface — deliberately, matching MedXpertQA. The declaration is a
    # promise the SDK trusts BEFORE spend: declaring one without serving the route lets a
    # corrective-loop run pass the pre-spend gate, burn paid turns, then die. Declare it only
    # together with the handler; `grading.verdict` is the parser it would use.
)

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASES_ROUTE",
    "CASE_COUNT",
    "CASE_EVALUATION_ROUTE",
    "CHECK_ROUTE",
    "CONTRACTEVAL",
    "DATASET_URL",
    "REVISION",
    "ROUTE_PREFIX",
    "compute_revision",
    "install_contracteval",
]
