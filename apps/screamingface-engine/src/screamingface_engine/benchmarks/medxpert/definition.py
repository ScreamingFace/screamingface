"""MedXpertQA (Text) as one Engine-owned, judge-free Benchmark.

FEATURE: expert-level medical multiple choice — 2,450 questions, one letter each, graded by
string comparison. The first benchmark whose grading spends NO judge tokens.

INVARIANT — the exchange is TWO candidate invocations. Turn 1 reasons freely; turn 2 sends only
the trigger, so the model completes "…the answer is ___" and its commitment comes FIRST. That
message layout, not any instruction, is what makes the official first-match extraction correct.
A one-shot prompt with the trigger appended produces letter-LAST essays that the same parser
misreads: measured at 35.5% against a true 70.2%.

NAMED DEVIATION — the two-turn exchange is imposed at the CANDIDATE BOUNDARY. The Engine invokes
`$candidate` as an opaque recipe (`ensemble/policy.py`: the client compiles the whole candidate
expression, the Engine "contributes generic invocation"), so a benchmark cannot reach inside a
Fusion. For a solo model this reproduces the official protocol exactly. For a Fusion it does not:
a per-member implementation runs two-turn inside each member and shows the synthesiser their full
analyses, which is not expressible here. Fusion numbers from this benchmark are therefore not
comparable to a per-member implementation, and the description says so.

References:
    - Paper: https://arxiv.org/abs/2501.18362
    - Dataset: https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA
    - Official harness: https://github.com/TsinghuaC3I/MedXpertQA (eval/)
"""

from __future__ import annotations

from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    FailurePolicy,
    candidate_invocation,
)
from screamingface_engine.benchmarks.medxpert.prompts import (
    COT_PROMPT_TEMPLATE,
    COT_TRIGGER_TEMPLATE,
)
from screamingface_engine.benchmarks.medxpert.revision_inputs import (
    DATASET,
    DATASET_CONFIG,
    DATASET_REVISION,
    DATASET_SPLIT,
    PREPARER_REVISION,
    PROTOCOL_REVISION,
)
from screamingface_engine.benchmarks.protocol import (
    CASE_SOURCE,
    EVALUATION_PROTOCOL_REVISION,
    attempt_source,
    evaluation_protocol,
)
from screamingface_engine.benchmarks.provenance import FrontierScore, HumanBaseline
from screamingface_engine.benchmarks.shared_grading.incremental_routes import (
    CASE_COUNT_SOURCE,
    CASE_INDEX_SOURCE,
    EXECUTION_SOURCE,
)
from screamingface_engine.benchmarks.shared_grading.serving import (
    CASE_RESULT_SUFFIX,
    GRADED_SUFFIX,
    benchmark_routes,
    compute_benchmark_revision,
)
from url4 import Node, RelUrl, Text, VarRef, expr, src
from url4.peer.server import Url4Node

BENCHMARK_ID = "medxpert"
ASSET_BUNDLE_ID = BENCHMARK_ID
CASE_COUNT = 2450
DATASET_URL = "https://huggingface.co/datasets/TsinghuaC3I/MedXpertQA"
# INVARIANT: grading is retrieval-free — the answer key is a fixed letter, and a model that
# searched would be answering a different question from the one the leaderboard asks.
CANDIDATE_WEB_SEARCH = False
# WHY "withhold" (OME-1642): a Case that never got a valid grade counts 0 over every selected
# Case, the same as an empty ANSWER, which the official empty-prediction verdict grades 0.0
# (`aggregate._scored`). Coverage still shows the graded count beside the score. One constant,
# read by the declaration and by the revision, so the two cannot drift.
FAILURE_POLICY: FailurePolicy = "withhold"


def compute_revision(
    *,
    dataset_revision: str = DATASET_REVISION,
    cot_template: str = COT_PROMPT_TEMPLATE,
    trigger_template: str = COT_TRIGGER_TEMPLATE,
    failure_policy: FailurePolicy = FAILURE_POLICY,
) -> str:
    """Fingerprint this benchmark into the 16 hex characters its routes carry.

    WHY the prompt templates are hashed: this benchmark has no judge, so the prompt is the only
    thing between a model and its score. A changed template is a changed benchmark and must
    re-address every route — otherwise already-recorded submissions would silently become
    incomparable. The failure policy is hashed for the same reason (OME-1642): a ``withhold``
    score is a different number from the same answers, so it gets its own revision.
    """

    return compute_benchmark_revision(
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
        # WHY conditional (OME-1642): only withhold moves the revision, the same rule as the
        # imported rows' fingerprint pin.
        *(("failure_policy=withhold",) if failure_policy == "withhold" else ()),
    )


REVISION = compute_revision()

_ROUTES = benchmark_routes(BENCHMARK_ID, REVISION)
ROUTE_PREFIX = _ROUTES.prefix
CASES_ROUTE = _ROUTES.cases
CASE_GRADE_ROUTE = _ROUTES.case_evaluation
AGGREGATE_ROUTE = _ROUTES.aggregate
# The turn-2 model input, built by code from the question, turn 1 and the trigger (spec §3.2).
COMMIT_PROMPT_ROUTE = f"{ROUTE_PREFIX}/commit-prompt"
REASONING_SOURCE = "reasoning"
COMMIT_PROMPT_SOURCE = "commit_prompt"


def _build(case_count: int) -> Node:
    """Build the two-turn MedXpertQA expression (spec §3.2).

    Reading the body in order: ask the Candidate to reason over the ready-made CoT prompt;
    build the commit prompt from the question, that reasoning and the trigger; ask the SAME
    Candidate to commit; record both turns as the Case row; grade it as soon as it finishes.
    """

    def case_value(field: str) -> Node:
        return VarRef("item", (field,))

    def sibling(name: str) -> Node:
        return VarRef(name, ())

    # Turn 1 — free reasoning. The cases file prepares the ready-made CoT prompt.
    reasoning = candidate_invocation(
        "$item.cot_prompt", case_count=case_count, web_search=CANDIDATE_WEB_SEARCH
    )
    # INVARIANT: the turn-2 bytes are `json.dumps({"question", "reasoning", "trigger"})`, the
    # model input the retired struct context produced, so stored replies still serve it.
    commit_prompt = expr(
        src(case_value("input"), name="question"),
        src(sibling(REASONING_SOURCE), name=REASONING_SOURCE),
        src(case_value("trigger"), name="trigger"),
        intent=RelUrl(COMMIT_PROMPT_ROUTE),
    )
    # Turn 2 — the commit; it holds the answer being graded. The model finishes the trigger
    # sentence, so the letter leads.
    commit = candidate_invocation(
        f"${COMMIT_PROMPT_SOURCE}", case_count=case_count, web_search=CANDIDATE_WEB_SEARCH
    )
    execution = expr(
        src(VarRef("item", ()), name=CASE_SOURCE, weight=0.0),
        src(sibling(REASONING_SOURCE), name=REASONING_SOURCE),
        src(sibling(attempt_source(1)), name=attempt_source(1)),
        intent=RelUrl(CASE_GRADE_ROUTE),
    )
    return evaluation_protocol(
        cases_route=CASES_ROUTE,
        steps=(
            src(reasoning, name=REASONING_SOURCE, weight=0.0),
            src(commit_prompt, name=COMMIT_PROMPT_SOURCE, weight=0.0),
            src(commit, name=attempt_source(1), weight=0.0),
            src(execution, name=EXECUTION_SOURCE, weight=0.0),
            src(VarRef("index", ()), name=CASE_INDEX_SOURCE, weight=0.0),
            src(Text(str(case_count)), name=CASE_COUNT_SOURCE, weight=0.0),
        ),
        case_terminal=AGGREGATE_ROUTE + CASE_RESULT_SUFFIX,
        run_terminal=AGGREGATE_ROUTE + GRADED_SUFFIX,
        selected_case_count=case_count,
        available_case_count=CASE_COUNT,
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
        "accuracy over every case run, reported beside the fraction actually answered — a case "
        "the model leaves unanswered, or that fails, counts as wrong. "
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
        # See FAILURE_POLICY (OME-1642).
        failure_policy=FAILURE_POLICY,
        # WHY "multi_turn": the benchmark invokes the Candidate twice per Case — reason, then
        # commit. Declared because it doubles the invocation cost and changes what a Fusion entrant
        # is asked to do (the exchange wraps the ensemble, not each member).
        interaction="multi_turn",
        # Expert-level medical questions frontier models still visibly fail (OME-1257).
        difficulty="hard",
    ),
    # AIDEV-NOTE: no check_surface — deliberately. The declaration is a promise the SDK trusts
    # BEFORE spend: with one present, a corrective-loop run passes the pre-spend gate, burns paid
    # candidate turns, then dies on a route `runtime.install` never serves. With none, the SDK
    # refuses the loop up front (check_surface_missing). Declare it only together with the
    # handler — `grading.extract_letter`/`grade` are the parsers it should use.
    # Benchmark Provenance (OME-1455); sources in the PR 3 table.
    paper_url="https://arxiv.org/abs/2501.18362",
    authors="Zuo et al., 2025",
    citation=(
        "@misc{zuo2025medxpertqabenchmarkingexpertlevelmedical,\n"
        "      title={MedXpertQA: Benchmarking Expert-Level Medical Reasoning and Und"
        "erstanding}, \n"
        "      author={Yuxin Zuo and Shang Qu and Yifei Li and Zhangren Chen and Xuek"
        "ai Zhu and Ermo Hua and Kaiyan Zhang and Ning Ding and Bowen Zhou},\n"
        "      year={2025},\n"
        "      eprint={2501.18362},\n"
        "      archivePrefix={arXiv},\n"
        "      primaryClass={cs.AI},\n"
        "      url={https://arxiv.org/abs/2501.18362}, \n"
        "}"
    ),
    harness_url=(
        "https://github.com/TsinghuaC3I/MedXpertQA/tree/5f1db162d0d2b03d62da2d4fe086076a36105e18/eval"
    ),
    license="MIT",
    license_note="TsinghuaC3I/MedXpertQA dataset card.",
    content_warning="Expert medical questions, including graphic clinical detail.",
    # Human baseline: "Expert (Pre-Licensed)", Text overall, paper Table 4 — an estimate from
    # exam-taker score distributions, not a sitting of this set
    human_baseline=HumanBaseline(score=0.426, source_url="https://arxiv.org/abs/2501.18362"),
    # Frontier score: MedXpertQA Text accuracy (10-option MCQ, 2,450 questions), Comparison r….
    frontier_score=FrontierScore(
        score=0.715,
        model="Gemini 3.1 Pro",
        source_url="https://benchlm.ai/benchmarks/medxpertqatext",
        as_of="2026-04",
    ),
    notebook="11_medxpert",
)

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASES_ROUTE",
    "CASE_COUNT",
    "CASE_GRADE_ROUTE",
    "COMMIT_PROMPT_ROUTE",
    "MEDXPERT",
    "REVISION",
    "compute_revision",
    "install_medxpert",
]
