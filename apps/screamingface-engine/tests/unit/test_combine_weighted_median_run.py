"""An SDK median block weighted by a field signal runs in the Engine (E4b, WM#15).

FEATURE: ``sf.Reduce("median", weights=sf.signal("field:confidence"))`` compiles to a Candidate
that the Engine runs; a member with confidence 0 is dropped and never becomes the nearest pick.
STORY: as an author, I trust a confident member more, and a member I mark as unsure does not vote.
INVARIANT: the record names ``weighted_median@1`` and the participants, and the chosen member is
one of the participants.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"


@pytest.mark.asyncio
async def test_engine_runs_median_block_weighted_by_field_confidence() -> None:
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
    assert combine["reducer"] == "median"
    assert combine["operators"] == [
        "json_field@1",
        "numeric@1",
        "weighted_median@1",
        "nearest@1",
    ]
    assert combine["median"] == "60"
    assert combine["chosen"] == ["member_4"]
    assert [m["weight"] for m in combine["members"]] == [None, 0.2, 0.2, 0.6]
    assert combine["signal"] == {"key": "field:confidence", "order": None}
