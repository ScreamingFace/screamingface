"""Both HealthBench benchmarks — registry, revisions, and the expression contract.

Mirrors `healthbench/definition.py` 1:1: what the two benchmarks SHARE is asserted once, then
each benchmark gets its own section. Every test names its benchmark, because "the benchmark" is
ambiguous now and a failure report has to say which one broke.

INVARIANT under test: a benchmark's protocol identity (template bytes, judge pinning, case
selection, scoring rule) is frozen into its revision and its rendered expression — any
drift must fail here before it can ship a different benchmark under the same name. The two
benchmarks differ in case selection and the final clip, and in NOTHING else.
"""

from __future__ import annotations

# OME-932 (owner-approved): early graded-results transport is additive; grading
# and semantic revision pins remain unchanged to preserve ranked submissions.
import hashlib

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.healthbench.definition import (
    HEALTHBENCH_PROFESSIONAL,
    HEALTHBENCH_WORST30,
    PROFESSIONAL_CASE_COUNT,
    PROFESSIONAL_CASE_IDS,
    PROFESSIONAL_VARIANT,
    WORST30_VARIANT,
)
from screamingface_engine.benchmarks.healthbench.prompts import GRADER_TEMPLATE
from screamingface_engine.benchmarks.healthbench.revision_inputs import CHECK_CRITERION, JUDGE_MODEL
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS, WORST30_HF_IDS
from url4.core.grammar import parse

# WHY: byte-parity with OpenAI simple-evals' GRADER_TEMPLATE (verified against the
# vendored reference at authoring time). Any edit — even fixing the reference's own
# typos — breaks grading parity and must be a deliberate protocol revision.
GRADER_TEMPLATE_SHA = "2adffd51fd259554ebcd036ad1072d4aa2b7ce3aec2bbffe36271f911632ed3c"

_BENCHMARKS = (HEALTHBENCH_WORST30, HEALTHBENCH_PROFESSIONAL)


def _url4(benchmark, limit=None) -> str:
    value = benchmark.resource(limit)["url4"]
    assert isinstance(value, str)
    return value


# ── Shared by both benchmarks ────────────────────────────────────────────────────────────


def test_the_grader_template_is_byte_pinned() -> None:
    assert hashlib.sha256(GRADER_TEMPLATE.encode()).hexdigest() == GRADER_TEMPLATE_SHA


def test_every_benchmark_pins_the_judge_identically() -> None:
    """INVARIANT: case selection and the final clip are the ONLY differences.

    Asserted over both benchmarks at once, so adding a third one cannot quietly ship a
    differently-pinned judge under the HealthBench name.
    """

    for benchmark in _BENCHMARKS:
        rendered = _url4(benchmark)
        # Empty intent — the Runner maps a non-empty intent to a SYSTEM message and the
        # official professional judge sends none.
        assert f"/{JUDGE_MODEL}?web_search=false&max_tokens=4096&q=($item.grader_prompt)!''" in (
            rendered
        )
        # Bounded fresh-sample retries ride the source annotation.
        assert ";retry=2" in rendered
        # No temperature pin anywhere in the judge call (provider default, per the
        # official ResponsesSampler reasoning branch).
        assert "temperature" not in rendered


def test_every_benchmark_invokes_the_candidate_without_retrieval() -> None:
    for benchmark in _BENCHMARKS:
        assert "/benchmarks/candidate?web_search=false" in _url4(benchmark)


def test_every_benchmark_expression_renders_and_reparses() -> None:
    for benchmark in _BENCHMARKS:
        rendered = _url4(benchmark)
        parse(rendered)
        # S-RT1: the whole benchmark must stay far under transport-hostile sizes — the
        # per-item fan-out is built Engine-side, not pre-expanded into the address.
        # 525 Cases must therefore render no larger than 157 do.
        assert len(rendered) < 4_000


# ── Benchmark 1 — the worst-30% challenge ────────────────────────────────────────────────


def test_the_worst30_benchmark_is_registered_under_its_id() -> None:
    assert BUILTIN_BENCHMARKS.get("healthbench-worst30") is HEALTHBENCH_WORST30


def test_the_worst30_subset_is_the_frozen_157() -> None:
    assert len(WORST30_HF_IDS) == 157
    assert len(set(WORST30_HF_IDS)) == 157
    assert len(WORST30_CASE_IDS) == 157


def test_the_worst30_routes_are_revision_pinned() -> None:
    assert WORST30_VARIANT.revision in _url4(HEALTHBENCH_WORST30)


def test_the_worst30_revision_is_frozen_against_refactors() -> None:
    """INVARIANT: the worst-30% benchmark's address may not move by accident.

    Every route this benchmark serves carries this hash, and the scoreboard seeds it by hand
    (`apps/scoreboard/charts/scoreboard/values.yaml`). A refactor that reshuffles how the
    revision is computed must land on the SAME value; a deliberate protocol change updates
    this literal AND re-seeds the benchmark in the same breath.
    """

    assert WORST30_VARIANT.revision == "39cfd96b068f7230"


def test_both_healthbench_benchmarks_link_the_openai_healthbench_dataset() -> None:
    # WHY the literal, on both benchmarks: the leaderboard renders this as a clickable target for
    # the public. The shared suite can only check that benchmarks sharing a bundle agree — and
    # both benchmarks read one constant, so they would agree on a wrong value too (OME-1095).
    assert HEALTHBENCH_WORST30.dataset_url == "https://huggingface.co/datasets/openai/healthbench"
    assert HEALTHBENCH_PROFESSIONAL.dataset_url == HEALTHBENCH_WORST30.dataset_url


def test_a_limit_slices_the_worst30_run() -> None:
    limited = HEALTHBENCH_WORST30.resource(3)
    assert limited["case_count"] == 157
    assert "iteration.slice=0:3" in _url4(HEALTHBENCH_WORST30, 3)
    assert ")!'3'" in _url4(HEALTHBENCH_WORST30, 3)


# ── Benchmark 2 — the full professional variant ─────────────────────────────────────────────


def test_the_professional_benchmark_is_registered_under_its_id() -> None:
    assert BUILTIN_BENCHMARKS.get("healthbench-professional") is HEALTHBENCH_PROFESSIONAL
    assert PROFESSIONAL_VARIANT.id == "healthbench-professional"


def test_the_professional_benchmark_serves_every_prepared_case() -> None:
    # WHY 1..525 with no gaps: prepare.py numbers Cases by their 1-based position in the
    # HF file, so "the whole benchmark" IS the contiguous range — any hole would mean a filter.
    assert PROFESSIONAL_CASE_COUNT == 525
    assert PROFESSIONAL_CASE_IDS == tuple(range(1, 526))
    assert HEALTHBENCH_PROFESSIONAL.case_count == 525


def test_the_professional_routes_are_revision_pinned() -> None:
    assert PROFESSIONAL_VARIANT.revision in _url4(HEALTHBENCH_PROFESSIONAL)


def test_the_two_benchmarks_have_separate_addresses() -> None:
    # INVARIANT: worst30 keeps its own revision and routes — an existing submission can
    # never be re-interpreted as a professional-benchmark submission, or vice versa.
    assert PROFESSIONAL_VARIANT.revision != WORST30_VARIANT.revision
    professional = _url4(HEALTHBENCH_PROFESSIONAL)
    assert f"/benchmarks/healthbench-professional/{PROFESSIONAL_VARIANT.revision}" in professional
    assert "healthbench-worst30" not in professional
    assert WORST30_VARIANT.revision not in professional


def test_a_limit_slices_the_professional_run_without_redefining_the_benchmark() -> None:
    limited = HEALTHBENCH_PROFESSIONAL.resource(3)
    # The benchmark still IS the 525-case benchmark; a smoke run just executes fewer of its Cases.
    assert limited["case_count"] == 525
    assert limited["selected_case_count"] == 3
    assert "iteration.slice=0:3" in _url4(HEALTHBENCH_PROFESSIONAL, 3)
    assert ")!'3'" in _url4(HEALTHBENCH_PROFESSIONAL, 3)


# AIDEV-NOTE (OME-1513): the name is frozen by the test-change rule; what it checks now is that
# the offer is OFF — Draft Feedback is a per-Benchmark owner decision (owner rule 2026-10-07),
# and today only IFEval carries one. The check-surface route is still served, not advertised.
def test_the_professional_check_surface_sits_under_its_own_prefix() -> None:
    # Capability parity with worst30 still holds, in the OFF direction: neither Benchmark
    # advertises an offer, and each one's (unadvertised) route sits under its own prefix.
    assert HEALTHBENCH_PROFESSIONAL.check_surface is None
    assert HEALTHBENCH_WORST30.check_surface is None
    assert PROFESSIONAL_VARIANT.routes.check_surface == (
        f"/benchmarks/{PROFESSIONAL_VARIANT.id}/{PROFESSIONAL_VARIANT.revision}"
        f"/check-surface/{CHECK_CRITERION}"
    )
