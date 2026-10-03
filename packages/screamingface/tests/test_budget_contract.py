"""The SDK decodes the Budget state the real Engine writes (OME-1289 E4a gap-closure, unit 12).

The Engine's own test (``test_budget_contract_fixture.py``) builds ``budget_cases.json`` from the
real records and pins it. This test only READS that file: a contract fixture, not an oracle. The
SDK must decode every state strictly and write it back unchanged, key order included, so the two
hand-written mirrors cannot drift apart.

A missing file FAILS when the Engine app is present; the test is skipped only when the Engine app
directory is absent (an installed run).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

from screamingface.budget import BudgetState

_CASES = COMBINE_CONTRACT / "budget_cases.json"
_EXPECTED_NAMES = {"usd_three_calls", "usd_cache_hit", "tokens", "unpriced", "overrun", "refused"}


def _cases() -> dict[str, Any]:
    assert _CASES.is_file(), f"missing Engine contract fixture {_CASES}"
    return json.loads(_CASES.read_text(encoding="utf-8"))


@requires_engine_app
def test_the_engine_fixture_holds_the_six_states() -> None:
    assert set(_cases()) == _EXPECTED_NAMES


@requires_engine_app
@pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
def test_an_engine_budget_decodes_and_round_trips_exactly(name: str) -> None:
    wire = _cases()[name]

    decoded = BudgetState.from_dict(wire)

    assert isinstance(decoded, BudgetState)
    assert json.dumps(decoded.to_dict()) == json.dumps(wire)
