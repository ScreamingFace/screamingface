# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The Case Digest: one fingerprint over exactly what Case Preparation writes (spec R5).

INVARIANT: the digest is computed from the same records the writer writes, so a Case that
differs on disk always has a different digest, and nothing else can move it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine_inspect.prepare import (  # noqa: E402
    PreparedCase,
    _write_cases,
    case_digest,
)

_PREPARED: list[PreparedCase] = [
    {
        "case": {"id": 1, "case_id": "1", "input": "What is 6 times 7?"},
        "grading_material": {"target": "42"},
    },
    {
        "case": {"id": 2, "case_id": "2", "input": "Wie viel ist 2 plus 2? — vier"},
        "grading_material": {"target": "4"},
    },
]


def test_case_digest_is_pinned_so_its_definition_cannot_drift_silently() -> None:
    """WHY a literal: every Task-replay declaration stores this value. A change to the
    serialisation (key order, separators, escaping) would SKIP every such Benchmark."""

    assert case_digest(_PREPARED) == (
        "765b395557508c36f4e5cf19ec9c4bb4936ca38301fbcd889aa46191735725a4"
    )


def test_case_digest_moves_when_any_written_field_or_the_order_moves() -> None:
    changed_target: list[PreparedCase] = [
        _PREPARED[0],
        {**_PREPARED[1], "grading_material": {"target": "5"}},
    ]
    reordered: list[PreparedCase] = [_PREPARED[1], _PREPARED[0]]

    assert case_digest(changed_target) != case_digest(_PREPARED)
    assert case_digest(reordered) != case_digest(_PREPARED)


def test_written_files_are_utf8_so_the_digest_matches_what_is_on_disk(tmp_path: Path) -> None:
    """Review Focus 3: non-ASCII text is written as UTF-8, never as \\u escapes."""

    _write_cases(_PREPARED, tmp_path)

    assert "— vier" in (tmp_path / "cases.json").read_text(encoding="utf-8")
    assert (tmp_path / "targets" / "2.json").read_text(encoding="utf-8") == '{"target":"4"}'


def test_case_digest_is_the_same_before_and_after_a_json_round_trip() -> None:
    """INVARIANT: a Case Digest means one thing wherever it is computed.

    WHY: JSON turns integer keys into strings, and strings sort differently (2 < 10, but
    "10" < "2"). Without normalising, Cases whose metadata has integer keys would seal to
    one digest in the child and another after the parent reads result.json back, and that
    Benchmark would go SKIPPED at every build (found in review of PR #1150).
    """

    prepared: list[PreparedCase] = [
        {
            "case": {"id": 1, "case_id": "1", "input": "Which page?"},
            "grading_material": {"target": "A", "metadata": {2: "two", 10: "ten"}},
        }
    ]
    round_tripped: list[PreparedCase] = json.loads(json.dumps(prepared))

    assert case_digest(prepared) == case_digest(round_tripped)
