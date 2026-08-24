"""The GDPval text-subset metric — points earned over points winnable, and the plain mean.

INVARIANT under test: an unscorable Case yields ``None``, never ``0.0``. "We could not score
this" and "the answer scored zero" are different facts, and collapsing them turns an
infrastructure failure into a plausible model weakness.

INVARIANT under test: the exam mean is PLAIN — no clip. GDPval's official metric is an expert
pairwise win rate, so there is no published convention to line up with; inventing a floor would
imply one exists.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.gdpval.scoring import case_score, mean


def test_all_positive_criteria_hit_scores_one() -> None:
    assert case_score([5, 3], {1: True, 2: True}) == 1.0


def test_missing_a_positive_criterion_scores_the_earned_fraction() -> None:
    assert case_score([5, 3], {1: True, 2: False}) == pytest.approx(5 / 8)


def test_a_penalty_subtracts_without_widening_the_denominator() -> None:
    # WHY: only POSITIVE points are winnable. A perfect answer earns every plus and triggers no
    # penalty, so penalties are points you can lose, never points you can win.
    #   winnable = 5 + 3 = 8 ; earned = 5 + (-3) = 2 ; 2/8
    assert case_score([5, 3, -3], {1: True, 2: False, 3: True}) == pytest.approx(2 / 8)


def test_a_score_may_go_negative() -> None:
    # INVARIANT: no clamp. GDPval rubrics carry penalties down to -85; a genuinely harmful
    # answer must be able to rank below one that said nothing.
    assert case_score([2, -10], {1: False, 2: True}) == pytest.approx(-5.0)


def test_no_positive_criterion_judged_is_unscorable_not_zero() -> None:
    assert case_score([-10], {1: True}) is None


def test_an_empty_verdict_set_is_unscorable() -> None:
    assert case_score([5, 3], {}) is None


def test_verdicts_outside_the_rubric_are_ignored() -> None:
    # WHY: the judge never sees rubric ids; the Engine stamps them. A stray id is a bug
    # elsewhere and must not silently widen this Case's denominator.
    assert case_score([5], {1: True, 99: True}) == 1.0


def test_only_judged_criteria_enter_the_denominator() -> None:
    # A partially judged Case divides by what was actually judged.
    assert case_score([5, 3], {1: True}) == 1.0


def test_mean_averages_graded_cases() -> None:
    assert mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)


def test_mean_ignores_unscorable_cases() -> None:
    # INVARIANT: an unscorable Case must not be averaged in as a zero — that would let a judge
    # outage depress a candidate's exam score.
    assert mean([1.0, None, 0.0]) == pytest.approx(0.5)


def test_mean_of_no_graded_cases_is_none() -> None:
    assert mean([None, None]) is None
    assert mean([]) is None


def test_mean_is_not_clipped() -> None:
    # INVARIANT: no floor at zero. HealthBench's professional board clips because the official
    # HealthBench metric does; GDPval has no such published convention.
    assert mean([-0.4, -0.2]) == pytest.approx(-0.3)


# --- reporting statistics -------------------------------------------------------------------


def test_sample_stdev_of_fewer_than_two_values_is_zero() -> None:
    from screamingface_engine.benchmarks.gdpval.scoring import sample_stdev

    assert sample_stdev([]) == 0.0
    assert sample_stdev([0.5]) == 0.0


def test_sample_stdev_uses_the_n_minus_one_denominator() -> None:
    # WHY pinned: population stdev of [0, 1] is 0.5; the sample form is 0.7071. A silent switch
    # would understate spread on exactly the small partial runs a reader sees most.
    from screamingface_engine.benchmarks.gdpval.scoring import sample_stdev

    assert sample_stdev([0.0, 1.0]) == pytest.approx(0.7071067811865476)


def test_verdict_coverage_is_the_judged_fraction() -> None:
    from screamingface_engine.benchmarks.gdpval.scoring import verdict_coverage

    assert verdict_coverage(3, 4) == pytest.approx(0.75)


def test_verdict_coverage_of_nothing_is_zero_not_a_division_error() -> None:
    from screamingface_engine.benchmarks.gdpval.scoring import verdict_coverage

    assert verdict_coverage(0, 0) == 0.0
