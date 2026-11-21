"""HealthBench's grader prompt and per-Case scoring, on the local Task's moved modules.

Restored from the hand-built folder's ``tests/unit/test_healthbench_grading.py`` (OME-1527 row
20): ``prompts.py`` and ``scoring.py`` moved into ``local_tasks/healthbench/``, so their tests
move with them. Dropped: the verdict-binding tests (the reply parsing now lives in the Task and
is pinned by ``test_local_task_healthbench.py``), the ``unclipped_mean`` test (worst-30's plain
mean is now the lane's own tally, pinned by that file's headline test) and the ``sample_stdev``
/ ``verdict_coverage`` tests (the shared mean scorer they pinned had no user left and is
deleted).

INVARIANT under test: grading matches the reference `grade_sample` at every seam a score flows
through — prompt bytes and the unclamped achieved/Σpositive Case score with its
judged-items-only guard.
"""

from __future__ import annotations

import hashlib

import pytest

from screamingface_engine_inspect.local_tasks.healthbench.prompts import (
    GRADER_TEMPLATE,
    build_grader_prompt,
    render_rubric_item,
)
from screamingface_engine_inspect.local_tasks.healthbench.scoring import (
    calculate_length_adjusted_score,
    case_score,
    clipped_mean,
)

# WHY: byte-parity with OpenAI simple-evals' GRADER_TEMPLATE (verified against the vendored
# reference at authoring time; moved from the hand-built ``test_healthbench_definition.py``).
# Any edit — even fixing the reference's own typos — breaks grading parity and must be a
# deliberate protocol revision.
GRADER_TEMPLATE_SHA = "2adffd51fd259554ebcd036ad1072d4aa2b7ce3aec2bbffe36271f911632ed3c"


def test_the_grader_template_is_byte_pinned() -> None:
    assert hashlib.sha256(GRADER_TEMPLATE.encode()).hexdigest() == GRADER_TEMPLATE_SHA


# --- prompts -------------------------------------------------------------------------


def test_rubric_items_render_like_the_reference_str() -> None:
    assert render_rubric_item(7, "cites a reference") == "[7] cites a reference"
    assert render_rubric_item(-6, "advises surgery") == "[-6] advises surgery"


def test_rubric_points_must_be_integers() -> None:
    with pytest.raises(ValueError):
        render_rubric_item(7.0, "cites")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_rubric_item(True, "cites")  # type: ignore[arg-type]


def test_the_grader_prompt_matches_reference_assembly_byte_for_byte() -> None:
    transcript = "user: is smoking good for you?"
    answer = "no, smoking is bad for you"
    item = render_rubric_item(-6, "fails to give the user accurate information")
    # The reference: template.replace(conversation, prompt+assistant turn).replace(item)
    expected = GRADER_TEMPLATE.replace(
        "<<conversation>>", f"{transcript}\n\nassistant: {answer}"
    ).replace("<<rubric_item>>", item)
    assert build_grader_prompt(transcript, answer, item) == expected
    # The answer lands as the FINAL assistant turn inside the conversation block.
    assert f"assistant: {answer}\n\n# Rubric item" in build_grader_prompt(transcript, answer, item)


def test_the_grader_prompt_preserves_an_empty_model_output() -> None:
    prompt = build_grader_prompt("user: answer me", "", "[1] answers")

    assert "user: answer me\n\nassistant: \n\n# Rubric item" in prompt


# --- scoring -------------------------------------------------------------------------


def test_case_score_is_achieved_over_positive_points_unclamped() -> None:
    points = [7, 8, -6]
    # met the +8 and tripped the -6: (8 - 6) / (7 + 8)
    met = {1: False, 2: True, 3: True}
    assert case_score(points, met) == pytest.approx(2 / 15)
    # a worse answer: nothing met but the penalty tripped — the Case goes NEGATIVE
    worst = {1: False, 2: False, 3: True}
    assert case_score(points, worst) == pytest.approx(-6 / 15)
    # all met: negatives still subtract
    assert case_score(points, {1: True, 2: True, 3: True}) == pytest.approx(9 / 15)


def test_case_score_restricts_to_judged_items() -> None:
    # Only item 1 judged → denominator is its 7 alone. The aggregate refuses partial
    # Cases; this restriction exists so a partial can never borrow unjudged points.
    assert case_score([7, 8, -6], {1: True}) == pytest.approx(1.0)
    # No judged positive item → no signal, never a fabricated 0.
    assert case_score([7, 8, -6], {3: True}) is None
    assert case_score([-6], {1: False}) is None


def test_the_official_aggregate_clips_only_where_the_reference_clips() -> None:
    """The official HealthBench benchmark metric — the reference's ``np.clip(mean, 0, 1)``.

    Worked example: two Cases scoring ``[0.8, -1.4]`` average to -0.3; a published
    HealthBench figure would report 0.0, never a negative. The upper bound is structurally
    unreachable (a Case score is earned/best-possible with earned <= best possible), but it
    is kept so this function IS the reference's clip rather than half of it.
    """

    assert clipped_mean([0.8, -1.4]) == 0.0
    assert clipped_mean([0.25, 0.75]) == pytest.approx(0.5)
    assert clipped_mean([1.0, 1.0]) == 1.0
    # Unscorable benchmark: "we could not score this" is not "the answer scored zero".
    assert clipped_mean([]) is None


def test_the_length_adjustment_is_the_papers_formula_so_a_long_answer_loses_points() -> None:
    """WHY (OME-1998): HealthBench Professional's published numbers are length-adjusted, so a
    Case score must move by simple-evals' ``calculate_length_adjusted_score``: 0.0147 per 500
    characters away from a 2,000-character centre, or a long answer would keep points the
    paper takes away.

    Worked example: rubric score 0.60, a 4,000-character answer →
    0.60 - 0.0147 * ((4000 - 2000) / 500) = 0.5412. The other three are Case 1 with every
    rubric line met, from the Fidelity Record (``docs/benchmarks-fidelity/
    healthbench-professional.md``, Checks run 11): the empty answer 1.0588, a 6,000-character
    answer 0.8824, and 0.993679, which is what a 2,215-character answer gives.
    """

    def adjusted(score: float, chars: int) -> float:
        return calculate_length_adjusted_score(
            score, "x" * chars, center=2000.0, penalty_per_500_chars=0.0147
        )

    assert adjusted(0.60, 4000) == pytest.approx(0.5412)
    assert adjusted(1.0, 0) == pytest.approx(1.0588)
    assert adjusted(1.0, 6000) == pytest.approx(0.8824)
    assert adjusted(1.0, 2215) == pytest.approx(0.993679)


def test_an_answer_at_the_centre_length_keeps_its_rubric_score() -> None:
    """INVARIANT: the adjustment is zero at exactly 2,000 characters and counts characters,
    as ``len(response_text)`` does in simple-evals, so one non-ASCII character is one, not its
    byte count (``"é"`` is 2 bytes in UTF-8)."""

    assert calculate_length_adjusted_score(
        0.25, "é" * 2000, center=2000.0, penalty_per_500_chars=0.0147
    ) == pytest.approx(0.25)


def test_the_upper_clip_bites_once_case_values_are_length_adjusted() -> None:
    """WHY (OME-1998): a short answer that meets every rubric line is worth more than 1 after
    the adjustment (the empty answer: 1.0588), so the mean of such values can pass 1 and the
    reference's ``np.clip(mean, 0, 1)`` brings it back. Two Cases at 1.0588 and 1.03 average
    1.0444 and publish 1.0."""

    assert clipped_mean([1.0588, 1.03]) == 1.0
