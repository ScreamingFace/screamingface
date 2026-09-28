"""DRACO private grading assets fail closed."""

import json

import pytest

from screamingface_engine.benchmarks.draco import assets
from screamingface_engine.benchmarks.draco.errors import AggregateError

_RUBRIC = {
    "sections": [
        {"id": "accuracy", "criteria": [{"id": "a1", "weight": 1, "requirement": "correct"}]}
    ]
}


def test_missing_rubrics_directory_raises_rather_than_scoring_nothing(tmp_path) -> None:
    with pytest.raises(AggregateError, match="no rubrics"):
        assets.load_rubrics(tmp_path / "absent")


def test_an_empty_rubrics_directory_raises(tmp_path) -> None:
    (tmp_path / "rubrics").mkdir()

    with pytest.raises(AggregateError, match="no rubrics"):
        assets.load_rubrics(tmp_path / "rubrics")


def test_rubrics_load_keyed_by_case_id(tmp_path) -> None:
    (tmp_path / "7.json").write_text(json.dumps(_RUBRIC), encoding="utf-8")

    assert set(assets.load_rubrics(tmp_path)) == {7}
