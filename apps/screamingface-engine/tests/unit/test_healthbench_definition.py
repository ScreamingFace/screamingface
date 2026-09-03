"""Both HealthBench boards — registry, revisions, and the expression contract.

Mirrors `healthbench/definition.py` 1:1: what the two boards SHARE is asserted once, then
each board gets its own section. Every test names its board, because "the exam" is
ambiguous now and a failure report has to say which one broke.

INVARIANT under test: a board's protocol identity (template bytes, judge pinning, case
selection, scoring rule) is frozen into its revision and its rendered expression — any
drift must fail here before it can ship a different exam under the same name. The two
boards differ in case selection and the final clip, and in NOTHING else.
"""

from __future__ import annotations

import hashlib

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.healthbench.definition import (
    HEALTHBENCH_PROFESSIONAL,
    HEALTHBENCH_WORST30,
    PROFESSIONAL_CASE_COUNT,
    PROFESSIONAL_CASE_IDS,
    PROFESSIONAL_EXAM,
    WORST30_EXAM,
)
from screamingface_engine.benchmarks.healthbench.pins import CHECK_CRITERION, JUDGE_MODEL
from screamingface_engine.benchmarks.healthbench.prompts import GRADER_TEMPLATE
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS, WORST30_HF_IDS
from url4.core.grammar import parse

# WHY: byte-parity with OpenAI simple-evals' GRADER_TEMPLATE (verified against the
# vendored reference at authoring time). Any edit — even fixing the reference's own
# typos — breaks grading parity and must be a deliberate protocol revision.
GRADER_TEMPLATE_SHA = "2adffd51fd259554ebcd036ad1072d4aa2b7ce3aec2bbffe36271f911632ed3c"

_BOARDS = (HEALTHBENCH_WORST30, HEALTHBENCH_PROFESSIONAL)


def _url4(benchmark, limit=None) -> str:
    value = benchmark.resource(limit)["url4"]
    assert isinstance(value, str)
    return value


# ── Shared by both boards ────────────────────────────────────────────────────────────


def test_the_grader_template_is_byte_pinned() -> None:
    assert hashlib.sha256(GRADER_TEMPLATE.encode()).hexdigest() == GRADER_TEMPLATE_SHA


def test_every_board_pins_the_judge_identically() -> None:
    """INVARIANT: case selection and the final clip are the ONLY differences.

    Asserted over both boards at once, so adding a third one cannot quietly ship a
    differently-pinned judge under the HealthBench name.
    """

    for board in _BOARDS:
        rendered = _url4(board)
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


def test_every_board_invokes_the_candidate_without_retrieval() -> None:
    for board in _BOARDS:
        assert "/benchmarks/candidate?web_search=false" in _url4(board)


def test_every_board_expression_renders_and_reparses() -> None:
    for board in _BOARDS:
        rendered = _url4(board)
        parse(rendered)
        # S-RT1: the whole exam must stay far under transport-hostile sizes — the
        # per-item fan-out is built Engine-side, not pre-expanded into the address.
        # 525 Cases must therefore render no larger than 157 do.
        assert len(rendered) < 4_000


# ── Board 1 — the worst-30% challenge ────────────────────────────────────────────────


def test_the_worst30_board_is_registered_under_its_id() -> None:
    assert BUILTIN_BENCHMARKS.get("healthbench-worst30") is HEALTHBENCH_WORST30


def test_the_worst30_subset_is_the_frozen_157() -> None:
    assert len(WORST30_HF_IDS) == 157
    assert len(set(WORST30_HF_IDS)) == 157
    assert len(WORST30_CASE_IDS) == 157


def test_the_worst30_routes_are_revision_pinned() -> None:
    assert WORST30_EXAM.revision in _url4(HEALTHBENCH_WORST30)


def test_the_worst30_revision_is_frozen_against_refactors() -> None:
    """INVARIANT: the worst-30% board's address may not move by accident.

    Every route this board serves carries this hash, and the scoreboard seeds it by hand
    (`apps/scoreboard/charts/scoreboard/values.yaml`). A refactor that reshuffles how the
    revision is computed must land on the SAME value; a deliberate protocol change updates
    this literal AND re-seeds the board in the same breath.
    """

    assert WORST30_EXAM.revision == "39cfd96b068f7230"


def test_both_healthbench_boards_link_the_openai_healthbench_dataset() -> None:
    # WHY the literal, on both boards: the leaderboard renders this as a clickable target for
    # the public. The shared suite can only check that boards sharing a bundle agree — and
    # both boards read one constant, so they would agree on a wrong value too (OME-1095).
    assert HEALTHBENCH_WORST30.dataset_url == "https://huggingface.co/datasets/openai/healthbench"
    assert HEALTHBENCH_PROFESSIONAL.dataset_url == HEALTHBENCH_WORST30.dataset_url


def test_a_limit_slices_the_worst30_run() -> None:
    limited = HEALTHBENCH_WORST30.resource(3)
    assert limited["case_count"] == 157
    assert "slice=0:3" in _url4(HEALTHBENCH_WORST30, 3)


# ── Board 2 — the full professional exam ─────────────────────────────────────────────


def test_the_professional_board_is_registered_under_its_id() -> None:
    assert BUILTIN_BENCHMARKS.get("healthbench-professional") is HEALTHBENCH_PROFESSIONAL
    assert PROFESSIONAL_EXAM.id == "healthbench-professional"


def test_the_professional_board_serves_every_baked_case() -> None:
    # WHY 1..525 with no gaps: prepare.py numbers Cases by their 1-based position in the
    # HF file, so "the whole exam" IS the contiguous range — any hole would mean a filter.
    assert PROFESSIONAL_CASE_COUNT == 525
    assert PROFESSIONAL_CASE_IDS == tuple(range(1, 526))
    assert HEALTHBENCH_PROFESSIONAL.case_count == 525


def test_the_professional_routes_are_revision_pinned() -> None:
    assert PROFESSIONAL_EXAM.revision in _url4(HEALTHBENCH_PROFESSIONAL)


def test_the_two_boards_have_separate_addresses() -> None:
    # INVARIANT: worst30 keeps its own revision and routes — an existing submission can
    # never be re-interpreted as a professional-board submission, or vice versa.
    assert PROFESSIONAL_EXAM.revision != WORST30_EXAM.revision
    professional = _url4(HEALTHBENCH_PROFESSIONAL)
    assert f"/benchmarks/healthbench-professional/{PROFESSIONAL_EXAM.revision}" in professional
    assert "healthbench-worst30" not in professional
    assert WORST30_EXAM.revision not in professional


def test_a_limit_slices_the_professional_run_without_redefining_the_board() -> None:
    limited = HEALTHBENCH_PROFESSIONAL.resource(3)
    # The board still IS the 525-case exam; a smoke run just executes fewer of its Cases.
    assert limited["case_count"] == 525
    assert limited["selected_case_count"] == 3
    assert "slice=0:3" in _url4(HEALTHBENCH_PROFESSIONAL, 3)


def test_the_professional_check_surface_sits_under_its_own_prefix() -> None:
    # Capability parity with worst30 (owner decision, 2026-08-20): a corrective_loop
    # recipe runs on either board, under the SAME criterion and threshold.
    surface = HEALTHBENCH_PROFESSIONAL.check_surface
    assert surface is not None
    assert surface.check_route == (
        f"/benchmarks/{PROFESSIONAL_EXAM.id}/{PROFESSIONAL_EXAM.revision}"
        f"/check-surface/{CHECK_CRITERION}"
    )
    assert surface.expected_check_cost == "paid"
    worst30_surface = HEALTHBENCH_WORST30.check_surface
    assert worst30_surface is not None
    assert surface.feedback_intent == worst30_surface.feedback_intent
