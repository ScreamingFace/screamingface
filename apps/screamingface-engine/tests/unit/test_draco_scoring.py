"""DRACO's exact per-case scoring arithmetic."""

from screamingface_engine.benchmarks.draco import case_results, grade, scoring

_RUBRIC = {
    "sections": [
        {
            "id": "Factual Accuracy",
            "criteria": [
                {"id": "a1", "weight": 2, "requirement": "cites a source"},
                {"id": "a2", "weight": 1, "requirement": "states the date"},
                {"id": "a3", "weight": -3, "requirement": "invents a statistic"},
            ],
        },
        {"id": "Presentation", "criteria": [{"id": "b1", "weight": 1, "requirement": "is terse"}]},
    ]
}


def _verdicts(**kwargs: bool) -> dict[str, bool]:
    return dict(kwargs)


def test_perfect_answer_scores_one() -> None:
    assert scoring.normalized_score(_RUBRIC, _verdicts(a1=True, a2=True, a3=False, b1=True)) == 1.0


def test_a_met_negative_criterion_subtracts_from_the_numerator() -> None:
    assert scoring.normalized_score(_RUBRIC, _verdicts(a1=True, a2=False, a3=True, b1=True)) == 0.0


def test_the_score_is_clamped_at_zero_not_negative() -> None:
    assert (
        scoring.normalized_score(_RUBRIC, _verdicts(a1=False, a2=False, a3=True, b1=False)) == 0.0
    )


def test_partial_credit_is_weight_aware() -> None:
    assert (
        scoring.normalized_score(_RUBRIC, _verdicts(a1=True, a2=False, a3=False, b1=False)) == 0.5
    )


def test_all_negative_rubric_returns_zero_rather_than_dividing_by_zero() -> None:
    rubric = {"sections": [{"id": "X", "criteria": [{"id": "n1", "weight": -1}]}]}

    assert scoring.normalized_score(rubric, {"n1": False}) == 0.0


def test_pass_rate_counts_avoided_negatives_as_correct() -> None:
    assert scoring.pass_rate(_RUBRIC, _verdicts(a1=True, a2=True, a3=False, b1=True)) == 1.0


def test_pass_rate_is_unweighted() -> None:
    assert scoring.pass_rate(_RUBRIC, _verdicts(a1=True, a2=False, a3=True, b1=True)) == 0.5


def test_axis_scores_are_per_section() -> None:
    axes = scoring.axis_scores(_RUBRIC, _verdicts(a1=True, a2=False, a3=True, b1=True))

    assert axes == {"Factual Accuracy": 0.0, "Presentation": 1.0}


def test_axis_pass_rates_are_unweighted_per_section() -> None:
    rates = scoring.axis_pass_rates(
        _RUBRIC,
        _verdicts(a1=True, a2=False, a3=False, b1=True),
    )

    assert rates == {"Factual Accuracy": 2 / 3, "Presentation": 1.0}


def test_an_unjudged_criterion_drops_out_of_both_numerator_and_denominator() -> None:
    judged = {"a1": True, "a3": False, "b1": True}

    assert scoring.score_case(_RUBRIC, [judged])["normalized_score"] == 1.0


def test_coverage_reports_the_judged_fraction() -> None:
    judged = {"a1": True, "a3": False, "b1": True}

    assert scoring.score_case(_RUBRIC, [judged])["coverage"] == 0.75


def test_runs_are_grouped_in_order_so_each_pass_scores_independently() -> None:
    verdicts = [
        {"case_id": 1, "criterion_id": "a1", "sequence": n, "criterion_status": status}
        for n, status in enumerate(("MET", "UNMET", "MET"), start=1)
    ]

    assert case_results.group_runs(verdicts) == [{"a1": True}, {"a1": False}, {"a1": True}]


def test_a_criterion_with_fewer_passes_drops_out_of_the_missing_run() -> None:
    verdicts = [
        {"case_id": 1, "criterion_id": "a1", "sequence": 1, "criterion_status": "MET"},
        {"case_id": 1, "criterion_id": "a1", "sequence": 2, "criterion_status": "MET"},
        {"case_id": 1, "criterion_id": "a2", "sequence": 1, "criterion_status": "MET"},
    ]

    assert case_results.group_runs(verdicts) == [{"a1": True, "a2": True}, {"a1": True}]


def test_score_case_means_the_runs_and_reports_the_spread() -> None:
    scored = scoring.score_case(
        _RUBRIC,
        [
            {"a1": True, "a2": True, "a3": False, "b1": True},
            {"a1": True, "a2": False, "a3": False, "b1": True},
        ],
    )

    assert scored["normalized_score"] == 0.875
    assert scored["normalized_score_sd"] == 0.1768
    assert scored["pass_rate"] == 0.875
    assert scored["pass_rate_sd"] == 0.1768
    assert scored["accuracy"] == 0.8333
    assert scored["accuracy_pass_rate"] == 0.8333
    assert scored["axis_scores"] == {"Factual Accuracy": 0.8333, "Presentation": 1.0}
    assert scored["axis_pass_rates"] == {
        "Factual Accuracy": 0.8333,
        "Presentation": 1.0,
    }
    assert scored["n_runs"] == 2


def test_a_rubric_without_a_factual_accuracy_axis_reports_unknown_not_zero() -> None:
    """Absence must not render as 0.0 — that reads as "0% factually accurate" on a perfect run."""
    rubric = {
        "sections": [
            {"id": "Presentation", "criteria": [{"id": "b1", "weight": 1, "requirement": "clear"}]}
        ]
    }

    scored = scoring.score_case(rubric, [{"b1": True}])

    assert scored["normalized_score"] == 1.0
    assert scored["accuracy"] is None
    assert scored["accuracy_pass_rate"] is None


def test_a_case_missing_the_accuracy_axis_is_skipped_by_the_candidate_mean() -> None:
    """A Case that never observed the axis must not drag the Candidate mean toward zero."""
    with_axis = {"grade": {"metrics": {"accuracy": 0.8}}}
    without_axis = {"grade": {"metrics": {"accuracy": None}}}

    assert grade._mean_optional_grade_metrics([with_axis, without_axis], "accuracy") == 0.8
    assert grade._mean_optional_grade_metrics([without_axis], "accuracy") is None


def test_a_single_run_reports_zero_spread() -> None:
    scored = scoring.score_case(_RUBRIC, [{"a1": True, "a2": True, "a3": False, "b1": True}])

    assert scored["normalized_score"] == 1.0
    assert scored["normalized_score_sd"] == 0.0
    assert scored["n_runs"] == 1
