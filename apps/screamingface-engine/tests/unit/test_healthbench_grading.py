"""HealthBench grading pieces — prompts, verdict binding, and pure scoring.

INVARIANT under test: grading matches the reference `grade_sample` at every seam a
score flows through — prompt bytes, strict-boolean acceptance, and the unclamped
achieved/Σpositive Case score with its judged-items-only guard.
"""

from __future__ import annotations

import statistics

import pytest

from screamingface_engine.benchmarks.healthbench.prompts import (
    GRADER_TEMPLATE,
    build_grader_prompt,
    render_rubric_item,
)
from screamingface_engine.benchmarks.healthbench.scoring import (
    case_score,
    clipped_mean,
    unclipped_mean,
)
from screamingface_engine.benchmarks.healthbench.verdict import bind, binding_key

# WHY the spine import: sample_stdev / verdict_coverage moved into the shared exam
# scorer (OME-1097) — the tests follow the production location of the code they pin.
from screamingface_engine.benchmarks.spine.exam import sample_stdev, verdict_coverage

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


# --- verdict binding -----------------------------------------------------------------


def test_binding_key_decodes_engine_ids() -> None:
    assert binding_key("12:3") == (12, 3)
    for bad in ("12", "0:1", "1:0", "a:b", ""):
        with pytest.raises(ValueError):
            binding_key(bad)


def test_a_fenced_json_reply_binds_as_a_valid_verdict() -> None:
    raw = '```json\n{"explanation": "met because…", "criteria_met": true}\n```'
    record = bind(raw, case_id=5, rubric_id=2, producer_id="judge")
    assert record["valid"] is True
    assert record["criteria_met"] is True
    assert record["case_id"] == 5
    assert record["rubric_id"] == 2
    assert record["raw_output"] == raw


def test_bare_json_and_preambled_json_bind_too() -> None:
    assert (
        bind('{"criteria_met": false}', case_id=1, rubric_id=1, producer_id="j")["criteria_met"]
        is False
    )
    preambled = 'Sure! {"explanation": "…", "criteria_met": false}'
    assert bind(preambled, case_id=1, rubric_id=1, producer_id="j")["valid"] is True


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("the answer is fine", "invalid_json"),
        ('["criteria_met", true]', "invalid_shape"),
        # WHY: the reference accepts ONLY `label is True or label is False`; a string
        # "true" or 1 must count as an invalid reply (retry, then loud row failure),
        # never as a verdict.
        ('{"criteria_met": "true"}', "invalid_criteria_met"),
        ('{"criteria_met": 1}', "invalid_criteria_met"),
        ('{"explanation": "no verdict"}', "invalid_criteria_met"),
    ],
)
def test_unusable_replies_stay_invalid_with_evidence(raw: str, reason: str) -> None:
    record = bind(raw, case_id=2, rubric_id=1, producer_id="j")
    assert record["valid"] is False
    assert record["reason"] == reason
    assert record["raw_output"] == raw  # the audit trail keeps the exact reply


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


def test_the_exam_mean_is_unclipped() -> None:
    # WHY: official HealthBench clips max(0, mean); on the worst-30% subset every
    # serious baseline mean is negative and the clip would flatten the leaderboard
    # to 0.00 — the challenge keeps the raw mean.
    assert unclipped_mean([-0.4, -0.1]) == pytest.approx(-0.25)
    assert unclipped_mean([]) is None


def test_stdev_is_sample_not_population() -> None:
    values = [0.1, 0.5, 0.9]
    assert sample_stdev(values) == pytest.approx(statistics.stdev(values))
    assert sample_stdev([0.5]) == 0.0


def test_verdict_coverage() -> None:
    assert verdict_coverage(3, 4) == pytest.approx(0.75)
    assert verdict_coverage(0, 0) == 0.0


def test_the_official_aggregate_clips_only_where_the_reference_clips() -> None:
    """The official HealthBench exam metric — the reference's ``np.clip(mean, 0, 1)``.

    Worked example: two Cases scoring ``[0.8, -1.4]`` average to -0.3; a published
    HealthBench figure would report 0.0, never a negative. The upper bound is structurally
    unreachable (a Case score is earned/best-possible with earned <= best possible), but it
    is kept so this function IS the reference's clip rather than half of it.
    """

    assert clipped_mean([0.8, -1.4]) == 0.0
    assert clipped_mean([0.25, 0.75]) == pytest.approx(0.5)
    assert clipped_mean([1.0, 1.0]) == 1.0
    # Unscorable exam: "we could not score this" is not "the answer scored zero".
    assert clipped_mean([]) is None
