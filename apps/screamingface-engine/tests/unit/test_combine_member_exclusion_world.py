"""An SDK weighted median run excludes a member with no weight, in the Engine (E4b part 2 unit 2).

FEATURE: E4b part 2 unit 2, member exclusion (ans:Q3, P1, P4, P5, P13). The weighted median of
``sf.Reduce("median", weights=sf.signal("field:confidence"))`` records the member with confidence 0
as ``status "excluded"`` with the reason ``no_weight``, and the nearest pick never chooses it.
STORY: as a researcher, I see in the Case that a member I mark as unsure did not vote.
INVARIANT: the excluded member keeps its value, and the chosen member is one of the participants.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"


# WHY the name is the PRD name: this test checks the engine run record only. The SDK
# case.answers() half of this row is
# ST/test_member_exclusion.py::test_case_answers_show_the_excluded_status_and_value.
@pytest.mark.asyncio
async def test_sdk_run_shows_excluded_member_in_case_answers() -> None:
    path = _DATA / "weighted_median_confidence_candidate.url4"
    assert path.is_file(), "the url4 fixture is missing: run write_fixture() in the SDK"
    url4 = path.read_text("utf-8").removesuffix("\n")
    models = {
        "prov/alpha": ('{"answer":60,"confidence":0}', "0.001"),
        "prov/beta": ('{"answer":10,"confidence":0.2}', "0.001"),
        "prov/gamma": ('{"answer":20,"confidence":0.2}', "0.001"),
        "prov/delta": ('{"answer":60,"confidence":0.6}', "0.001"),
    }
    record = await run_candidate(url4, models, "miss")

    assert record["output"] == '{"answer":60,"confidence":0.6}'
    combine = operation(record, "op_synthesis_1")["combine"]
    assert [(m["status"], m["reason"]) for m in combine["members"]] == [
        ("excluded", "no_weight"),
        ("answered", None),
        ("answered", None),
        ("answered", None),
    ]
    assert combine["members"][0]["value"] == "60"
    assert combine["members"][0]["weight"] is None
    assert combine["chosen"] == ["member_4"]
    assert combine["result"] == {
        "member_id": "member_4",
        "value": "60",
        "status": "answered",
        "reason": None,
    }
    assert combine["dropped"] == 0
