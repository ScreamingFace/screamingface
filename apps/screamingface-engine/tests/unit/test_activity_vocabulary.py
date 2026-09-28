"""Stages and model detail share one vocabulary independent of the activity plugin."""

import pytest

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.stages import observe_stage


def test_only_four_stage_kinds_and_model_call_detail_exist():
    assert {kind.value for kind in ActivityKind} == {
        "case_loading",
        "answering",
        "grading",
        "aggregation",
        "model_call",
    }


def test_model_call_is_not_a_benchmark_stage():
    with pytest.raises(ValueError, match="model"):
        observe_stage(ActivityKind.MODEL_CALL)
