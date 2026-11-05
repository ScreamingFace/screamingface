"""The SDK decodes the consistency evidence the real Engine writes (E4b part 7, unit 2; CV#14).

The Engine's own test (``test_combine_consistency_contract.py``) builds
``consistency_evidence_cases.json`` from the real combine core and pins it. This test only READS
that file. It is a contract fixture, not an oracle: the SDK must decode every entry strictly and
write it back unchanged (contracts C4).

A missing file FAILS when the Engine app is present; the test is skipped only when the Engine app
directory is absent (an installed run).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.combine_evidence import CombineEvidence, CombineSampleCount

_CASES = COMBINE_CONTRACT / "consistency_evidence_cases.json"
_EXPECTED_NAMES = ("consistency_vote", "consistency_pick_default_match", "consistency_no_votes")


def _cases() -> dict[str, Any]:
    assert _CASES.is_file(), f"missing Engine contract fixture {_CASES}"
    return json.loads(_CASES.read_text(encoding="utf-8"))


@requires_engine_app
def test_the_engine_consistency_fixture_holds_the_three_scenarios() -> None:
    assert tuple(_cases()) == _EXPECTED_NAMES


@requires_engine_app
@pytest.mark.parametrize("name", _EXPECTED_NAMES)
def test_sdk_decodes_the_consistency_contract_cases(name: str) -> None:
    wire = _cases()[name]

    decoded = decode_combine_evidence(wire, f"Engine evidence {name}")

    assert isinstance(decoded, CombineEvidence)
    assert "consistency" in wire
    assert decoded.to_dict() == wire


@requires_engine_app
def test_sdk_reads_the_fixture_v_counts() -> None:
    decoded = decode_combine_evidence(_cases()["consistency_vote"], "Engine evidence")

    assert isinstance(decoded, CombineEvidence)
    assert decoded.consistency is not None
    assert tuple(decoded.consistency["cons"]) == (
        CombineSampleCount("member_1", 2, 4, 0),
        CombineSampleCount("member_2", 2, 2, 2),
        CombineSampleCount("member_3", None, 0, 4),
    )
