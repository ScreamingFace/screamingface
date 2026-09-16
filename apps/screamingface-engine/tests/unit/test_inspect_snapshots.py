# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The imported boards' asset snapshots — their formatting baked as data (spec §5.3).

INVARIANT the suite defends: prompt formatting reproduces the eval's own solver-chain
templates at bake time; the public booklet (``cases.json``) never carries a target;
the private ``targets/`` records hold exactly what the scorer shim needs (the target,
plus the choice texts for MCQ boards); and the mmlu shuffle is seeded — the baked
order is exam identity.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.prepare import (  # noqa: E402
    PrepareError,
    emit_gsm8k,
    emit_mmlu,
    mcq_prompt,
)

_GSM8K_ROWS: list[dict[str, Any]] = [
    {"question": "What is 6 times 7?", "answer": "6 * 7 = 42\n#### 42"},
    {"question": "A train travels 30 km twice. Total?", "answer": "30 + 30 = 60\n#### 60"},
]

_MMLU_ROWS: list[dict[str, Any]] = [
    {"question": "Pick B.", "choices": ["no", "yes", "never", "maybe"], "answer": 1},
    {"question": "Pick A.", "choices": ["yes", "no", "never", "maybe"], "answer": 0},
    {"question": "Pick D.", "choices": ["no", "never", "maybe", "yes"], "answer": 3},
]


# ── gsm8k ────────────────────────────────────────────────────────────────────


def test_gsm8k_snapshot_bakes_their_template_and_the_private_target(
    tmp_path: Path,
) -> None:
    summary = emit_gsm8k(_GSM8K_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert [case["id"] for case in cases] == [1, 2]
    assert all(case["case_id"] == str(case["id"]) for case in cases)
    # Their MATH_PROMPT_TEMPLATE wraps the verbatim question (imported prompt = data).
    assert "What is 6 times 7?" in cases[0]["input"]
    assert "ANSWER: $ANSWER" in cases[0]["input"]
    # INVARIANT: the public booklet never carries the answer key.
    assert "42" not in json.dumps(cases)
    target = json.loads((tmp_path / "targets" / "1.json").read_text(encoding="utf-8"))
    # Their record_to_sample rule: the target is the text after "####", stripped.
    assert target == {"target": "42"}
    assert summary["cases"] == 2


def test_gsm8k_snapshot_refuses_a_row_without_a_target(tmp_path: Path) -> None:
    with pytest.raises(PrepareError, match="case 1"):
        emit_gsm8k([{"question": "Q?", "answer": "no delimiter"}], tmp_path)


# ── mmlu ─────────────────────────────────────────────────────────────────────


def test_mcq_prompt_is_their_single_answer_template() -> None:
    prompt = mcq_prompt(_MMLU_ROWS[0])
    assert "ANSWER: $LETTER" in prompt
    assert "A) no" in prompt and "B) yes" in prompt and "D) maybe" in prompt
    assert "Pick B." in prompt


def test_mmlu_snapshot_bakes_letter_and_choices_privately(tmp_path: Path) -> None:
    emit_mmlu(_MMLU_ROWS, tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 3
    targets = [
        json.loads((tmp_path / "targets" / f"{case['id']}.json").read_text(encoding="utf-8"))
        for case in cases
    ]
    for target in targets:
        assert target["target"] in "ABCD"
        assert len(target["choices"]) == 4
    # INVARIANT: the booklet carries prompts only — the key stays in targets/.
    assert "target" not in json.dumps(cases)


def test_mmlu_snapshot_shuffles_deterministically(tmp_path: Path) -> None:
    """INVARIANT: the seeded order is exam identity — same rows, same seed, same order."""

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    emit_mmlu(_MMLU_ROWS, first_dir)
    emit_mmlu(_MMLU_ROWS, second_dir)
    first = (first_dir / "cases.json").read_text(encoding="utf-8")
    assert first == (second_dir / "cases.json").read_text(encoding="utf-8")
    # And the shuffle visibly leaves the subject-grouped dataset order.
    questions = [case["input"] for case in json.loads(first)]
    assert questions != [mcq_prompt(row) for row in _MMLU_ROWS]


def test_mmlu_snapshot_refuses_a_row_without_a_question(tmp_path: Path) -> None:
    """A malformed row fails the whole bake by case number, never a raw KeyError."""

    with pytest.raises(PrepareError, match="case 1"):
        emit_mmlu([{"choices": ["a", "b", "c", "d"], "answer": 0}], tmp_path)


# ── exam-size and re-bake guards (shared by both boards) ─────────────────────


@pytest.mark.parametrize(("emit", "rows"), [(emit_gsm8k, _GSM8K_ROWS), (emit_mmlu, _MMLU_ROWS)])
def test_wrong_sized_dataset_refuses_the_bake(emit: Any, rows: Any, tmp_path: Path) -> None:
    """INVARIANT: the pinned case count is exam identity — a config/revision typo that
    yields the wrong number of rows (0 included) must fail loudly, never bake a
    smaller exam with a green build."""

    with pytest.raises(PrepareError, match="pinned case count"):
        emit(rows, tmp_path, expected_cases=len(rows) + 1)


def test_rebake_into_a_used_directory_is_refused(tmp_path: Path) -> None:
    """INVARIANT: no orphan answer keys — a second bake into the same directory could
    leave stale targets/*.json from a previous, larger bake, so it is refused."""

    emit_gsm8k(_GSM8K_ROWS, tmp_path)
    with pytest.raises(PrepareError, match="non-empty"):
        emit_gsm8k(_GSM8K_ROWS, tmp_path)
