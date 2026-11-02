"""E4b changes neither report.v1 nor report-trace.v1 (E4b CS-D4).

CHAR (CS#10): passes before and after every E4b unit. Neither record lists reducer names or abstain
reasons, so a new reducer (``mean``) or a new abstain reason (``output_missing``) leaves both
frozen files as they are.
INVARIANT defended: the report-trace.v1 snapshot and the two report.v1 goldens keep their bytes
(SHA-256 below, taken from the files at e4b-combine-extensions 0b848c219).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize(
    ("name", "sha256"),
    [
        (
            "schemas/screamingface.report-trace.v1.json",
            "482fa302e2aed0e9a080d4465f115db857d021547ec2d3530b2d0c5a121ef459",
        ),
        (
            "report_v1_combine_report.json",
            "5a2fb135562809c5b4fea75f77e8b956b04f3e682266444789b2c1a020204eb6",
        ),
        (
            "report_v1_vote_median_report.json",
            "26c73070b80bb1ce95d8b34f03f1ada35c08a0152533775a8a081180f1a968b7",
        ),
    ],
)
def test_report_v1_and_trace_v1_snapshots_are_unchanged(name: str, sha256: str) -> None:
    assert hashlib.sha256((_DATA / name).read_bytes()).hexdigest() == sha256
