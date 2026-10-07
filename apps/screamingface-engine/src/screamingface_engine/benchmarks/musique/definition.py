"""MuSiQue-Ans as one Engine-owned, judge-free Benchmark.

FEATURE: multi-hop reading over given paragraphs — the 2,417 answerable dev Cases of MuSiQue.
Each question chains 2 to 4 facts from different paragraphs among 17 to 20, most of them
decoys. The model commits two lines (`Supporting paragraphs:`, `Answer:`), and the paper's own
scorer turns them into three Named Scores, so no Judge tokens are spent.

INVARIANT — our number means what the paper's number means: the Cases are byte-verified against
the reviewed dev file, the scorer is the paper's code copied verbatim, and every byte between the
two (the prompt) is inside the Benchmark Revision.

References:
    - Paper: Trivedi et al., TACL 2022 — https://aclanthology.org/2022.tacl-1.31/
    - Reference harness: https://github.com/StonyBrookNLP/musique (CC BY 4.0)
      @ 922ac98f19a201998dbdae6d7f2887a5258dbdeb
    - Case Source: https://huggingface.co/datasets/dgslibisey/MuSiQue
    - Spec: docs/spec/2026-10-07-OME-1475-musique-ans.md
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from screamingface_engine.benchmarks.contract import CANDIDATE_RESULT_SCHEMA
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    candidate,
)
from screamingface_engine.benchmarks.musique.prompts import (
    CASE_TEMPLATE,
    PARAGRAPH_SEPARATOR,
    PARAGRAPH_TEMPLATE,
)
from screamingface_engine.benchmarks.musique.revision_inputs import (
    DATASET,
    DATASET_FILE,
    DATASET_REVISION,
    DATASET_SHA256,
    EXPECTED_CASES,
    PREPARER_REVISION,
    PROTOCOL_REVISION,
    SCORER_REVISION,
)
from screamingface_engine.benchmarks.protocol import (
    EVALUATION_PROTOCOL_REVISION,
    build_evaluation_protocol,
    early_result,
    preserve_candidate_outcome,
)
from screamingface_engine.benchmarks.provenance import FrontierScore, HumanBaseline
from screamingface_engine.benchmarks.shared_grading.serving import (
    benchmark_routes,
    compute_benchmark_revision,
)
from url4 import Node, RelExpr, Text, expr, render, src, struct
from url4.peer.server import Url4Node

BENCHMARK_ID = "musique-ans"
# WHY a different id from the Benchmark's (spec D1): `musique-ans` leaves room for MuSiQue-Full,
# a different dataset, while a hyphen is not a Python module name — the package, the asset
# bundle and the SDK CLI name are all `musique`.
ASSET_BUNDLE_ID = "musique"
# WHY sourced from the pin and not a second literal: this value feeds the expression's
# `available_case_count`, and a copy here could drift from the count Case Preparation checks.
CASE_COUNT = EXPECTED_CASES
DATASET_URL = "https://huggingface.co/datasets/dgslibisey/MuSiQue"
# INVARIANT: the paper's setting gives the paragraphs. A model that searched the web would be
# answering the open-domain setting, a different exam (spec "Out of scope").
CANDIDATE_WEB_SEARCH = False

#: The upstream sha256 of the copied scorer files (`answer.py`, `support.py`, `metric.py` at
#: StonyBrookNLP/musique@922ac98f), as `vendor/__init__.py` records them and
#: `tests/unit/test_musique_vendor.py` holds the copies to. WHY in the Revision although
#: SCORER_REVISION names the commit: a re-copy from another commit that forgot to bump the pin
#: still has to move every route address.
SCORER_FILES_SHA256: tuple[str, ...] = (
    "10368f619b4d5ef5d83748c05a96c0afd332a14ab5c010740c98d58dfaefe974",
    "ac16c0daf458a6a4d6db97682c2340fe5b5936a947bf32c04dc3bf16406077c6",
    "c858d1bfda2f0b005065e87a402cd2f82154eb7eed5916845ae130759cc3a299",
)


def compute_revision(
    *,
    dataset: str = DATASET,
    dataset_file: str = DATASET_FILE,
    dataset_revision: str = DATASET_REVISION,
    dataset_sha256: str = DATASET_SHA256,
    expected_cases: int = EXPECTED_CASES,
    preparer_revision: str = PREPARER_REVISION,
    protocol_revision: str = PROTOCOL_REVISION,
    scorer_revision: str = SCORER_REVISION,
    case_template: str = CASE_TEMPLATE,
    paragraph_template: str = PARAGRAPH_TEMPLATE,
    paragraph_separator: str = PARAGRAPH_SEPARATOR,
    scorer_files_sha256: Sequence[str] = SCORER_FILES_SHA256,
) -> str:
    """Fingerprint this Benchmark into the 16 hex characters its routes carry.

    WHY everything between the dev file and a score: there is no Judge, so the Case Source
    bytes, the prompt bytes and the scorer bytes are the whole exam. A changed prompt changes
    what every Candidate is asked; a changed scorer changes what every reply earns. Either is a
    new Benchmark and must re-address every route. Only the advisory `MAX_TOKENS` stays out,
    because this Benchmark never applies it.

    Every keyword exists so `tests/unit/test_musique_definition.py` can prove its input is
    inside the hash; production calls this with the defaults.
    """

    return compute_benchmark_revision(
        dataset,
        dataset_file,
        dataset_revision,
        dataset_sha256,
        str(expected_cases),
        preparer_revision,
        protocol_revision,
        scorer_revision,
        EVALUATION_PROTOCOL_REVISION,
        CANDIDATE_RESULT_SCHEMA,
        case_template,
        paragraph_template,
        paragraph_separator,
        *scorer_files_sha256,
    )


REVISION = compute_revision()

_ROUTES = benchmark_routes(BENCHMARK_ID, REVISION)
ROUTE_PREFIX = _ROUTES.prefix
CASES_ROUTE = _ROUTES.cases
CHECK_ROUTE = _ROUTES.check
CASE_GRADE_ROUTE = _ROUTES.case_evaluation
AGGREGATE_ROUTE = _ROUTES.aggregate


def _build(case_count: int) -> Node:
    """Build the single-shot MuSiQue-Ans expression.

    One Candidate answer per Case, checked once. The whole Case input (paragraphs, question and
    the two-line instruction) is written into `$item.input` by Case Preparation, so there is
    nothing to assemble here.
    """

    candidate_invocation = candidate(
        "$item.input",
        case_id="$item.id",
        case_index="$index",
        case_count=str(case_count),
        web_search=CANDIDATE_WEB_SEARCH,
    )
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
                path=CASE_GRADE_ROUTE,
                # WHY a struct and not the bare record: the case-evaluation route is the
                # object-shaped `attempt_records_endpoint`; the array-shaped sibling rejects this
                # payload (OME-1126 live failure).
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


def install_musique(node: Url4Node, assets: Path) -> None:
    """Install the MuSiQue-Ans Cases, checker and reducers."""

    # Lazy import keeps the resource-only control plane free of runtime deps.
    from screamingface_engine.benchmarks.musique.runtime import install

    install(node, assets / ASSET_BUNDLE_ID)


MUSIQUE_ANS = Benchmark(
    id=BENCHMARK_ID,
    title="MuSiQue-Ans",
    description=(
        "2,417 multi-hop reading questions from the MuSiQue-Ans dev split (the test split's "
        "answers are withheld). Each question chains 2 to 4 facts, each fact sits in a "
        "different paragraph, and the model is given 17 to 20 numbered paragraphs, most of them "
        "decoys chosen to look relevant. It may reason first, then must end its reply with two "
        'lines: "Supporting paragraphs:" (the numbers of the paragraphs it used) and "Answer:" '
        "(the answer in as few words as possible). Grading is the paper's own scoring code, "
        "copied verbatim, so there is no Judge and no grading tokens. Three Named Scores per "
        "run: f1, the headline (token F1 against the answer and its accepted aliases), exact "
        "(exact match), and support_f1 (F1 of the cited paragraph numbers against the gold "
        "ones). A reply missing either line is still graded, and flagged. The Frontier Score, "
        "0.692 answer F1, is a fine-tuned retrieval pipeline's result on the test split, not a "
        "prompted model on dev, so our runs sit beside it rather than on the same scale. The "
        "dev set has been public since 2022 and may be in a model's training data."
    ),
    revision=REVISION,
    case_count=CASE_COUNT,
    build=_build,
    install=install_musique,
    focus="Multi-hop reading over decoy-filled paragraphs",
    dataset_url=DATASET_URL,
    declaration=BenchmarkDeclaration(
        # WHY "coverage_declare": a Case that never got a valid grade (an infrastructure
        # failure) is handled by the shared finalizer, which scores the gradeable subset and
        # publishes Coverage. A reply in the wrong format IS graded, and flagged.
        failure_policy="coverage_declare",
        # One Candidate invocation per Case.
        interaction="single_shot",
        # Human answer F1 78.0 against 49.8 for the paper's best model, and 69.2 for the best
        # published fine-tuned pipeline: real headroom on every axis (spec D1).
        difficulty="hard",
    ),
    # AIDEV-NOTE: no check_surface — spec D14, no Draft Feedback. The declaration is a promise
    # the SDK trusts BEFORE spend; declare one only together with its handler.
    # Benchmark Provenance (OME-1455); values and sources in the plan's "PR 3" provenance block.
    paper_url="https://aclanthology.org/2022.tacl-1.31/",
    authors="Trivedi et al., 2022",
    # WHY these fields: volume, pages and DOI as printed on the TACL article's first page.
    citation=(
        "@article{trivedi-etal-2022-musique,\n"
        '    title = "{M}u{S}i{Q}ue: Multihop Questions via Single-hop Question Composition",\n'
        '    author = "Trivedi, Harsh and Balasubramanian, Niranjan and Khot, Tushar and '
        'Sabharwal, Ashish",\n'
        '    journal = "Transactions of the Association for Computational Linguistics",\n'
        '    volume = "10",\n'
        '    year = "2022",\n'
        '    publisher = "MIT Press",\n'
        '    url = "https://aclanthology.org/2022.tacl-1.31/",\n'
        '    doi = "10.1162/tacl_a_00475",\n'
        '    pages = "539--554",\n'
        "}"
    ),
    homepage_url="https://github.com/StonyBrookNLP/musique",
    harness_url=(
        "https://github.com/StonyBrookNLP/musique/tree/922ac98f19a201998dbdae6d7f2887a5258dbdeb"
    ),
    license="CC-BY-4.0",
    license_note=(
        "MuSiQue data and code are CC BY 4.0; Cases are served from the byte-identical "
        "dgslibisey/MuSiQue mirror."
    ),
    # Human answer F1 on 125 sampled questions (TACL 2022, Table 3).
    human_baseline=HumanBaseline(score=0.78, source_url="https://aclanthology.org/2022.tacl-1.31/"),
    # Answer F1 in the official setting (given paragraphs only), test split, Table 4 of
    # arXiv 2308.08973v2 — the highest found (spec "Frontier Score").
    frontier_score=FrontierScore(
        score=0.692,
        model="Beam Retrieval (DeBERTa-large, beam size 2)",
        source_url="https://aclanthology.org/2024.naacl-long.96/",
        as_of="2024-06",
    ),
    notebook="15_musique",
)

__all__ = [
    "AGGREGATE_ROUTE",
    "ASSET_BUNDLE_ID",
    "BENCHMARK_ID",
    "CASES_ROUTE",
    "CASE_COUNT",
    "CASE_GRADE_ROUTE",
    "CHECK_ROUTE",
    "DATASET_URL",
    "MUSIQUE_ANS",
    "REVISION",
    "ROUTE_PREFIX",
    "SCORER_FILES_SHA256",
    "compute_revision",
    "install_musique",
]
