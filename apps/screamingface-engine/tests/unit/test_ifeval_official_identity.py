"""IFEval assets carry the OFFICIAL dataset identity — keys, file order, and text.

FEATURE: case ids are the official IFEval ``key`` values and ``cases.json`` preserves
the official file order, so every artifact joins directly to the official dataset;
prompts are verified (and, for the one known HF divergence, patched) against the
vendored official file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.ifeval.aggregate import (
    SCHEMA,
    AggregateError,
    aggregate,
    load_case_order,
)
from screamingface_engine.benchmarks.ifeval.case_evaluation import bind_case_evaluation
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.benchmarks.ifeval.prepare import (
    KNOWN_DIVERGENT_KEYS,
    PrepareError,
    build,
    official_rows,
    verify_against_official,
)


def test_the_ifeval_board_is_registered_under_its_id() -> None:
    """INVARIANT: this board is PUBLIC — dropping it is a leaderboard regression.

    The shared cross-benchmark tests iterate the registry, so a board deleted from
    `builtins.py` stops being iterated and they all still pass (OME-1095). Membership is
    pinned here, in the board's own module, where a new board costs one line.
    """

    assert BUILTIN_BENCHMARKS.get("ifeval") is IFEVAL


def test_the_ifeval_board_publishes_no_dataset_link() -> None:
    # WHY none: the dataset is vendored inside the Engine
    # (screamingface_engine.benchmarks.ifeval.vendor), so no single public URL is
    # authoritative. The shared suite cannot express this — "which boards have a link" is a
    # per-board editorial fact, so it is pinned beside the board that decides it.
    assert IFEVAL.dataset_url is None
    assert IFEVAL.focus


def _official(key: int) -> dict[str, object]:
    return next(row for row in official_rows() if row["key"] == key)


# --- build emits official identity ------------------------------------------------


def test_build_ids_are_the_official_keys_in_official_file_order(tmp_path: Path) -> None:
    """INVARIANT: artifacts join to the official dataset — case ids ARE the official
    keys and cases.json keeps the official file order, never a 1..n renumbering."""

    rows = official_rows()[:6]

    build(rows, tmp_path, expected_count=6)

    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    ids = [case["id"] for case in cases]
    assert ids == [row["key"] for row in rows]
    assert ids != list(range(1, len(rows) + 1))
    # The official keys are NOT ascending in file order — consumers must never
    # reconstruct the selection order by sorting ids.
    assert ids != sorted(ids)
    spec_files = {path.stem for path in (tmp_path / "instructions").glob("*.json")}
    assert spec_files == {str(case_id) for case_id in ids}


def test_key_2785_prompt_is_patched_to_the_official_text(tmp_path: Path) -> None:
    """INVARIANT: the one known HF divergence (key 2785 says "one placeholder" while
    its kwargs require 3) is patched — the emitted case and spec carry the OFFICIAL
    prompt, whose placeholder count matches the kwargs."""

    official = _official(2785)
    assert isinstance(official["prompt"], str)
    assert "at least 3 placeholders" in official["prompt"]
    hf_style = dict(
        official,
        prompt=official["prompt"].replace("at least 3 placeholders", "at least one placeholder"),
    )
    assert hf_style["prompt"] != official["prompt"]

    summary = build([hf_style], tmp_path, expected_count=1)

    assert summary["patched_keys"] == [2785]
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert cases == [{"id": 2785, "input": official["prompt"]}]
    spec = json.loads((tmp_path / "instructions" / "2785.json").read_text(encoding="utf-8"))
    assert spec["prompt"] == official["prompt"]
    assert "at least one placeholder" not in spec["prompt"]


# --- verification fails loudly on unknown drift ------------------------------------


def test_prompt_drift_on_an_unknown_key_fails_loudly() -> None:
    """INVARIANT: a prompt divergence on any key outside KNOWN_DIVERGENT_KEYS is a
    protocol event — verification raises instead of silently patching."""

    rows = [dict(row) for row in official_rows()[:2]]
    assert rows[1]["key"] not in KNOWN_DIVERGENT_KEYS
    rows[1]["prompt"] = f"{rows[1]['prompt']} (tampered)"

    with pytest.raises(PrepareError, match="unexpected keys"):
        verify_against_official(rows)


def test_instruction_or_kwargs_drift_fails_on_any_key() -> None:
    """INVARIANT: the graded surface (instruction ids + null-stripped kwargs) must
    match the official dataset exactly — even on the known prompt-divergent key."""

    drifted_ids = dict(official_rows()[0], instruction_id_list=["startend:quotation"])
    with pytest.raises(PrepareError, match="diverge"):
        verify_against_official([drifted_ids])

    official = _official(2785)
    assert isinstance(official["kwargs"], list)
    drifted_kwargs = dict(official, kwargs=[{"num_highlights": 99}, {"num_placeholders": 3}])
    with pytest.raises(PrepareError, match="diverge"):
        verify_against_official([drifted_kwargs])


# --- the selection order round-trips through cases.json ----------------------------


def test_load_case_order_returns_cases_json_ids_in_file_order(tmp_path: Path) -> None:
    """INVARIANT: cases.json is the ONLY source of "which case is collected row N" —
    ids come back in file order, not sorted."""

    (tmp_path / "cases.json").write_text(
        json.dumps([{"id": 30, "input": "a"}, {"id": 4, "input": "b"}]), encoding="utf-8"
    )

    assert load_case_order(tmp_path) == [30, 4]


def test_load_case_order_raises_on_a_missing_file(tmp_path: Path) -> None:
    """Same fail-loud rule as load_specs: incomplete assets never reach scoring."""

    with pytest.raises(AggregateError):
        load_case_order(tmp_path / "missing")


def test_load_case_order_raises_on_duplicate_ids(tmp_path: Path) -> None:
    """A duplicate id would grade two rows against one spec — refuse the assets."""

    (tmp_path / "cases.json").write_text(
        json.dumps([{"id": 7, "input": "a"}, {"id": 7, "input": "b"}]), encoding="utf-8"
    )

    with pytest.raises(AggregateError, match="duplicate"):
        load_case_order(tmp_path)


# --- aggregate binds rows via case_order, never sorted ids -------------------------

_ORDER_SPECS = {
    30: {"prompt": "No commas.", "instruction_id_list": ["punctuation:no_comma"]},
    4: {"prompt": "Use quotes.", "instruction_id_list": ["startend:quotation"]},
}


def _record(case_id: int) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "valid": True,
        "status": "completed",
        "answer": f"Answer {case_id}",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
        "instruction_id_list": _ORDER_SPECS[case_id]["instruction_id_list"],
        "descriptions": ["Fixture instruction"],
        "strict": [True],
        "loose": [True],
        "violations": [],
    }


def test_aggregate_grades_rows_in_cases_json_order_not_sorted_ids() -> None:
    """INVARIANT: the selection order comes from cases.json, never from sorted ids —
    with the non-ascending order [30, 4], row 0 is graded against spec 30 and row 1
    against spec 4; sorting the ids would bind every row to the wrong spec."""

    rows = json.dumps(
        [
            case_execution_payload(
                30,
                encode_candidate_invocation("Answer 30", "stop", None),
                [bind_case_evaluation(30, [_record(30)])],
            ),
            case_execution_payload(
                4,
                encode_candidate_invocation("Answer 4", "stop", None),
                [bind_case_evaluation(4, [_record(4)])],
            ),
        ]
    )

    result = aggregate(rows, _ORDER_SPECS, "ifeval", [30, 4], selected_case_count=2)

    assert result["score"] == 1.0
    assert [case["case_id"] for case in result["cases"]] == [30, 4]
    assert result["cases"][0]["output"] == "Answer 30"
    assert result["cases"][1]["output"] == "Answer 4"

    # The same rows against the SORTED order are corrupt, not ungradeable Cases.
    with pytest.raises(AggregateError, match="position 0"):
        aggregate(rows, _ORDER_SPECS, "ifeval", [4, 30], selected_case_count=2)
