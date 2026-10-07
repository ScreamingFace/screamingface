"""The MuSiQue-Ans Benchmark — identity, Benchmark Revision inputs, the expression, provenance.

INVARIANT under test: everything between the dev file and a score is inside the Benchmark
Revision. There is no Judge, so the Case Source bytes, the prompt bytes and the copied scorer
are the whole exam; a change to any one of them must re-address every route, or an expression
recorded against the old exam would resolve against a new one.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from test_musique_vendor import _UPSTREAM_SHA256

import screamingface_engine.benchmarks.musique.vendor as vendor
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS, BUILTIN_REGISTRATIONS
from screamingface_engine.benchmarks.musique import definition as benchmark
from screamingface_engine.benchmarks.musique import revision_inputs
from screamingface_engine.benchmarks.provenance import FrontierScore, HumanBaseline
from url4 import render
from url4.core.grammar import parse

#: Pins that never enter the Revision, each for a reason recorded at its definition.
_ADVISORY_PINS: frozenset[str] = frozenset({"MAX_TOKENS"})

#: The compute_revision inputs that are not pins in `revision_inputs`: the three prompt
#: template constants (prompts.py) and the copied scorer files' hashes (vendor/).
_NON_PIN_INPUTS: frozenset[str] = frozenset(
    {"case_template", "paragraph_template", "paragraph_separator", "scorer_files_sha256"}
)

#: A changed value for each non-text input; every other input is text and takes "different".
_CHANGED_VALUES: dict[str, object] = {"expected_cases": 9999, "scorer_files_sha256": ("0" * 64,)}


def _revision_inputs() -> list[str]:
    """Every keyword `compute_revision` accepts — one per identity input."""

    return list(inspect.signature(benchmark.compute_revision).parameters)


def test_every_identity_pin_is_an_input_of_the_revision() -> None:
    """INVARIANT: a pin added to `revision_inputs` without joining the hash would change the
    Cases or the scorer while every route kept its old address. Only the advisory token budget
    stays out, because the Benchmark never applies it."""

    pins: set[str] = {name.lower() for name in revision_inputs.__all__} - {
        name.lower() for name in _ADVISORY_PINS
    }

    assert pins == set(_revision_inputs()) - _NON_PIN_INPUTS


@pytest.mark.parametrize("name", _revision_inputs())
def test_changing_any_identity_input_changes_the_revision(name: str) -> None:
    """Each input, changed alone, moves the Revision — so none is merely accepted and dropped."""

    changed: Any = _CHANGED_VALUES.get(name, "different")

    assert benchmark.compute_revision(**{name: changed}) != benchmark.compute_revision()


def test_the_default_revision_is_the_published_one() -> None:
    assert benchmark.compute_revision() == benchmark.REVISION
    assert benchmark.MUSIQUE_ANS.revision == benchmark.REVISION


def test_the_revision_hashes_the_copied_scorer_files_as_they_were_reviewed() -> None:
    """The scorer's hashes in the Revision are the ones the vendor test holds the copied files
    to, so editing a copied file AND its pinned hash still moves the Revision."""

    assert set(benchmark.SCORER_FILES_SHA256) == set(_UPSTREAM_SHA256.values())
    for digest in benchmark.SCORER_FILES_SHA256:
        assert digest in (vendor.__doc__ or "")


def test_the_benchmark_serves_the_whole_dev_split() -> None:
    assert benchmark.CASE_COUNT == 2417
    assert benchmark.MUSIQUE_ANS.case_count == 2417


def test_the_benchmark_id_and_the_asset_bundle_differ_because_a_module_cannot_hold_a_hyphen() -> (
    None
):
    """Spec D1: `musique-ans` leaves room for MuSiQue-Full; the package is `musique`."""

    assert benchmark.MUSIQUE_ANS.id == "musique-ans"
    assert benchmark.ASSET_BUNDLE_ID == "musique"


def test_the_benchmark_is_registered_against_its_own_bundle() -> None:
    registration = next(r for r in BUILTIN_REGISTRATIONS if r.benchmark is benchmark.MUSIQUE_ANS)

    assert benchmark.MUSIQUE_ANS in tuple(BUILTIN_BENCHMARKS)
    assert registration.asset_bundle.id == "musique"


def test_every_route_carries_the_revision() -> None:
    """INVARIANT: an expression addressed to an old Revision never resolves against a changed
    Benchmark, which holds only while every route carries the Revision."""

    for route in (
        benchmark.CASES_ROUTE,
        benchmark.CHECK_ROUTE,
        benchmark.CASE_GRADE_ROUTE,
        benchmark.AGGREGATE_ROUTE,
    ):
        assert route.startswith(f"/benchmarks/musique-ans/{benchmark.REVISION}/")


def test_the_expression_parses() -> None:
    parse(render(benchmark.MUSIQUE_ANS.build(5)))


def test_the_expression_invokes_the_candidate_exactly_once() -> None:
    """INVARIANT: single_shot, as declared — one Candidate call per Case (spec Data Flow ④)."""

    assert render(benchmark.MUSIQUE_ANS.build(5)).count("/benchmarks/candidate") == 1


def test_the_candidate_reads_only_the_given_paragraphs() -> None:
    """The paper's setting gives the paragraphs; web search would answer a different exam (the
    open-domain setting, which the spec puts out of scope)."""

    assert "web_search=false" in render(benchmark.MUSIQUE_ANS.build(5))


def test_the_expression_uses_the_object_shaped_case_evaluation_payload() -> None:
    """REGRESSION (OME-1126): the array-shaped route rejects `{attempt_1: ...}`, and every Case
    then dies at grading after inference was paid for."""

    assert "case-evaluation({attempt_1: '$record'})" in render(benchmark.MUSIQUE_ANS.build(5))


def test_the_selected_case_count_reaches_the_iteration() -> None:
    """A `limit=N` run selects N Cases before admitting Candidate calls."""

    assert f"{benchmark.CASES_ROUTE}()!'5'" in render(benchmark.MUSIQUE_ANS.build(5))
    assert f"{benchmark.CASES_ROUTE}()!'50'" in render(benchmark.MUSIQUE_ANS.build(50))


def test_the_declaration_matches_what_the_benchmark_does() -> None:
    """One Candidate call per Case; a Case that never got a grade goes to the shared finalizer;
    hard because the paper's best model trails humans by a wide margin (spec D1)."""

    declaration = benchmark.MUSIQUE_ANS.declaration

    assert declaration.interaction == "single_shot"
    assert declaration.failure_policy == "coverage_declare"
    assert declaration.difficulty == "hard"


def test_no_check_surface_is_advertised() -> None:
    """Spec D14: no Draft Feedback. Advertising a surface without its handler lets a corrective
    loop pass the pre-spend gate and die after paying for turns."""

    assert benchmark.MUSIQUE_ANS.check_surface is None


def test_the_provenance_is_the_one_the_plan_reviewed() -> None:
    """Spec D13: the cover-sheet facts, verbatim from the plan's provenance block."""

    musique = benchmark.MUSIQUE_ANS

    assert musique.paper_url == "https://aclanthology.org/2022.tacl-1.31/"
    assert musique.authors == "Trivedi et al., 2022"
    assert musique.homepage_url == "https://github.com/StonyBrookNLP/musique"
    assert musique.harness_url == (
        "https://github.com/StonyBrookNLP/musique/tree/922ac98f19a201998dbdae6d7f2887a5258dbdeb"
    )
    assert musique.license == "CC-BY-4.0"
    assert musique.human_baseline == HumanBaseline(
        score=0.78, source_url="https://aclanthology.org/2022.tacl-1.31/"
    )
    assert musique.frontier_score == FrontierScore(
        score=0.692,
        model="Beam Retrieval (DeBERTa-large, beam size 2)",
        source_url="https://aclanthology.org/2024.naacl-long.96/",
        as_of="2024-06",
    )
    assert musique.notebook == "15_musique"
    assert musique.dataset_url == "https://huggingface.co/datasets/dgslibisey/MuSiQue"


def test_the_citation_is_the_tacl_article() -> None:
    citation: str = benchmark.MUSIQUE_ANS.citation  # type: ignore[assignment]

    assert citation.startswith("@article{")
    assert "Multihop Questions via Single-hop Question Composition" in citation
    assert "10.1162/tacl_a_00475" in citation


def test_the_description_says_what_a_reader_needs_before_quoting_a_score() -> None:
    """The cover sheet names the split, the two committed lines, the absence of a Judge, the
    three Named Scores, and the two reasons the Frontier Score is not our scale."""

    description: str = benchmark.MUSIQUE_ANS.description

    for phrase in (
        "dev split",
        "Supporting paragraphs:",
        "Answer:",
        "no Judge",
        "f1",
        "exact",
        "support_f1",
        "0.692",
        "test split",
        "training data",
    ):
        assert phrase in description, phrase
