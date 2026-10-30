"""The consistency evidence the SDK decodes is the evidence the Engine writes (E4b part 7; CV#13).

FEATURE: ``data/combine_contract/consistency_evidence_cases.json`` holds the canonical JSON of the
evidence the real combine core writes for three consistency scenarios: fixture V (a vote), fixture
W (a pick with the default match) and fixture V with no voter (CV-D5).
STORY: as a maintainer, I change the consistency record on one side and a test on the other side
fails, instead of the SDK decoder drifting from the Engine silently.
INVARIANT defended: this is a CONTRACT FIXTURE. The expected bytes are whatever the Engine writes
today, and the file pins them; the hand-computed records of the PRD are checked on the file too.
A NEW file, not ``evidence_cases.json`` (overview P20): part 6 builds in parallel, so the shared
37-case file and its count pins stay untouched. The SDK twin
(``packages/screamingface/tests/test_consistency_evidence_contract.py``) only READS this file.
A deliberate change is made by running this file as a script (``write_fixture()``) and reviewing
the diff. A missing fixture file FAILS here; it is never skipped.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from combine_consistency_support import (
    V_NO_VOTES_RECORD,
    V_OUTPUTS,
    V_RECORD,
    V_SAMPLES,
    W_OUTPUTS,
    W_RECORD,
    W_SAMPLES,
    context,
    outcome,
    v_spec,
    w_spec,
)
from test_combine_evidence_contract_fixture import canonical_evidence

from screamingface_engine.combine.evidence import CombineEvidence

FIXTURE = Path(__file__).parent / "data" / "combine_contract" / "consistency_evidence_cases.json"


def _consistency_vote() -> CombineEvidence:
    return outcome(v_spec(), context(outputs=V_OUTPUTS, samples=V_SAMPLES)).evidence


def _consistency_pick_default_match() -> CombineEvidence:
    return outcome(w_spec(), context(outputs=W_OUTPUTS, samples=W_SAMPLES)).evidence


def _consistency_no_votes() -> CombineEvidence:
    return outcome(v_spec(), context(panel="[]", samples=V_SAMPLES)).evidence


SCENARIOS: dict[str, Callable[[], CombineEvidence]] = {
    "consistency_vote": _consistency_vote,
    "consistency_pick_default_match": _consistency_pick_default_match,
    "consistency_no_votes": _consistency_no_votes,
}


def write_fixture() -> None:
    """Regenerate ``consistency_evidence_cases.json`` from the real core (run as a script)."""
    cases = {name: json.loads(canonical_evidence(build())) for name, build in SCENARIOS.items()}
    FIXTURE.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture() -> dict[str, Any]:
    assert FIXTURE.is_file(), f"missing contract fixture {FIXTURE}; run write_fixture()"
    loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_the_engine_consistency_evidence_is_the_fixture_byte_for_byte(name: str) -> None:
    pinned = _fixture()[name]

    assert canonical_evidence(SCENARIOS[name]()) == json.dumps(
        pinned, ensure_ascii=False, separators=(",", ":")
    )


def test_the_consistency_fixture_holds_exactly_the_three_scenarios() -> None:
    assert list(_fixture()) == list(SCENARIOS)


def test_the_consistency_fixture_holds_the_hand_computed_records() -> None:
    cases = _fixture()
    vote, pick, no_votes = (cases[name] for name in SCENARIOS)

    assert vote["consistency"] == {"cons": V_RECORD}
    assert [m["signals"] for m in vote["members"]] == [{"cons": 0.5}, {"cons": 1.0}, {"cons": None}]
    assert pick["consistency"] == {"cons": W_RECORD}
    assert [m["signals"]["cons"] for m in pick["members"]] == [0.6666666666666666, 0.0, 1.0]
    assert no_votes["consistency"] == {"cons": V_NO_VOTES_RECORD}
    assert no_votes["result"]["reason"] == "no_votes"


if __name__ == "__main__":
    write_fixture()
