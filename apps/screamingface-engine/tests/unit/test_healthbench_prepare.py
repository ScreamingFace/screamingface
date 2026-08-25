"""HealthBench preparer — the build-time gate between the HF dataset and the answer key.

INVARIANT under test: a dataset that moved under the frozen subset (missing id,
re-ordered rows) or that violates the grading contract (float points, no positive
item) FAILS THE BUILD — it can never bake a silently different answer key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.healthbench.prepare import (
    PrepareError,
    case_messages,
    emit,
    main,
    rubric_items,
)
from screamingface_engine.benchmarks.healthbench.subset import (
    WORST30_CASE_IDS,
    WORST30_HF_IDS,
)

_TOTAL_ROWS = 525


def test_cli_renders_the_current_preparation_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.healthbench.prepare._prepare",
        lambda _out: {
            "professional_cases": 525,
            "declared_worst30_cases": 157,
            "out": str(tmp_path),
        },
    )

    assert main(["--out", str(tmp_path)]) == 0
    assert capsys.readouterr().out == (
        f"healthbench: baked 525 cases into {tmp_path} "
        "— the professional board serves all 525, worst30 serves 157\n"
    )


def _synthetic_rows() -> list[dict[str, object]]:
    """525 rows honoring the frozen HF positions of the worst-30% ids."""

    by_position = dict(zip(WORST30_CASE_IDS, WORST30_HF_IDS, strict=True))
    rows = []
    for position in range(1, _TOTAL_ROWS + 1):
        rows.append(
            {
                "id": by_position.get(position, f"filler-{position}"),
                "conversation": {"messages": [{"role": "user", "content": f"question {position}"}]},
                "rubric_items": [
                    {"criterion_text": f"criterion {position}", "points": 5},
                    {"criterion_text": f"penalty {position}", "points": -2},
                ],
            }
        )
    return rows


def test_emit_bakes_public_cases_and_private_rubrics(tmp_path: Path) -> None:
    total, subset = emit(_synthetic_rows(), tmp_path)
    assert (total, subset) == (_TOTAL_ROWS, 157)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert [case["id"] for case in cases] == list(range(1, _TOTAL_ROWS + 1))
    # The input is the PLAIN-JSON candidate envelope (data form, not a url4 struct).
    first = json.loads(cases[0]["input"])
    assert first["schema"] == CANDIDATE_INPUT_SCHEMA
    assert first["messages"][0]["content"] == "question 1"
    # Privacy: no rubric text in the public file; the key lives in rubrics/ only.
    assert "criterion" not in (tmp_path / "cases.json").read_text(encoding="utf-8")
    rubric = json.loads((tmp_path / "rubrics" / "20.json").read_text(encoding="utf-8"))
    assert rubric["items"][0] == {"rubric_id": 1, "criterion": "criterion 20", "points": 5}


def test_a_missing_frozen_id_fails_the_build(tmp_path: Path) -> None:
    rows = _synthetic_rows()
    rows[WORST30_CASE_IDS[0] - 1]["id"] = "not-the-frozen-id"
    with pytest.raises(PrepareError, match="absent"):
        emit(rows, tmp_path)


def test_a_reordered_dataset_fails_the_build(tmp_path: Path) -> None:
    rows = _synthetic_rows()
    first, second = WORST30_CASE_IDS[0] - 1, WORST30_CASE_IDS[1] - 1
    rows[first]["id"], rows[second]["id"] = rows[second]["id"], rows[first]["id"]
    with pytest.raises(PrepareError, match="no longer matches"):
        emit(rows, tmp_path)


def test_float_points_fail_the_build(tmp_path: Path) -> None:
    row = {"rubric_items": [{"criterion_text": "c", "points": 7.0}]}
    with pytest.raises(PrepareError, match="integer"):
        rubric_items(row, 1)


def test_a_rubric_without_a_positive_item_fails_the_build(tmp_path: Path) -> None:
    row = {"rubric_items": [{"criterion_text": "penalty", "points": -6}]}
    with pytest.raises(PrepareError, match="no positive-points"):
        rubric_items(row, 1)


def test_conversations_must_carry_usable_turns() -> None:
    with pytest.raises(PrepareError, match="not JSON"):
        case_messages({"conversation": "not-json"}, 1)
    with pytest.raises(PrepareError, match="messages list"):
        case_messages({"conversation": {"turns": []}}, 1)
    with pytest.raises(PrepareError, match="role and content"):
        case_messages({"conversation": {"messages": [{"role": "user"}]}}, 1)
    with pytest.raises(PrepareError, match="no messages"):
        case_messages({"conversation": {"messages": []}}, 1)


def test_a_dataset_that_gained_a_row_fails_the_build(tmp_path: Path) -> None:
    """INVARIANT: the professional board declares exactly 525 Cases (OME-903).

    The frozen-position check above only proves the worst-30% rows did not MOVE. A row
    appended at the END leaves every frozen position intact, so it sails through — and the
    image would then bake a 526-Case exam under a 525-Case identity. The count is its own
    gate.
    """

    rows = _synthetic_rows()
    rows.append(
        {
            "id": "one-row-too-many",
            "conversation": {"messages": [{"role": "user", "content": "question 526"}]},
            "rubric_items": [{"criterion_text": "criterion 526", "points": 5}],
        }
    )
    with pytest.raises(PrepareError, match="525"):
        emit(rows, tmp_path)
