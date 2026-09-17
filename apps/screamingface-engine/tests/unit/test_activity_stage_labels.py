"""Researcher-facing stage labels are simpler than the diagnostic kind vocabulary."""

import pytest

from screamingface_engine.activity.contract import ActivityKind, message


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        (ActivityKind.CASE_LOADING, "Loading cases"),
        (ActivityKind.ANSWERING, "Answering"),
        (ActivityKind.GRADING_PREPARE, "Grading"),
        (ActivityKind.GRADING_CHECK, "Grading"),
        (ActivityKind.GRADING_REDUCE, "Grading"),
        (ActivityKind.AGGREGATION, "Aggregating"),
    ],
)
def test_stage_messages_use_the_four_researcher_labels(kind, label):
    assert message(kind, "started") == f"{label} started"
    assert message(kind, "completed") == f"{label} completed"


def test_model_call_remains_a_diagnostic_detail():
    assert message(ActivityKind.MODEL_CALL, "retrying") == "Model call retrying"
