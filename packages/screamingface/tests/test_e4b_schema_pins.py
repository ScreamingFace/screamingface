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
            "687605763d666ce2ad69ef6e4c9420eb8ffa3f13e7e8a574f8a662510884567c",
        ),
        (
            "report_v1_combine_report.json",
            "85fb1253ee37e8debd0efcb5380309e5ac271aed613bfece466dc523e5de911a",
        ),
        (
            "report_v1_vote_median_report.json",
            "47c658fbaf7d126da62fb64464c04879b2ae2c70f5f03aa9050c744bb38bc390",
        ),
    ],
)
def test_report_v1_and_trace_v1_snapshots_are_unchanged(name: str, sha256: str) -> None:
    assert hashlib.sha256((_DATA / name).read_bytes()).hexdigest() == sha256
