"""An SDK-written judge Filter runs in the engine, then the writer (E4b unit 6, FJ#12).

FEATURE: ``sf.Filter(where=sf.signal("score:judge") >= 7, judge=sf.Judge(..., returns="scores"))``
followed by a writer. The url4 file under ``data/combine_contract/`` is what the SDK
compiles (the SDK drift guard keeps it byte-equal), so this test runs the real compiler output
through the mocked gateway of ``_signal_world.run_candidate``.
STORY: as a benchmark author, the writer gets the Case question and only the drafts that the judge
scored at or over 7, in author order.
INVARIANT defended: the judge is called once for the whole panel, the writer never sees a dropped
member's text, the judge's ``binding`` param never reaches the gateway, and the combine evidence
names the judge's scores and the kept members.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"

# WHY the cost on every call: the mocked gateway needs a cost for each model reply
_MODELS = {
    "prov/alpha": ("alpha draft", "0.001"),
    "prov/beta": ("beta draft", "0.001"),
    "prov/gamma": ("gamma draft", "0.001"),
    "prov/judge": ('{"member_1": 9, "member_2": 4, "member_3": 7}', "0.001"),
    "prov/writer": ("final", "0.001"),
}


@pytest.mark.asyncio
async def test_engine_runs_sdk_filter_by_judge_then_writer() -> None:
    # WHY read inside the test: a missing fixture fails this test, not the whole module's collection
    url4 = (_DATA / "filter_judge_candidate.url4").read_text(encoding="utf-8").removesuffix("\n")
    seen: list[dict[str, Any]] = []

    record = await run_candidate(url4, _MODELS, "miss", on_request=seen.append)

    assert record["status"] == "completed"
    assert record["output"] == "final"
    # three members, one judge call for the whole panel, and the writer
    assert len(seen) == 5
    assert sum(call["model"] == "prov/judge" for call in seen) == 1
    assert sum(call["model"] == "prov/writer" for call in seen) == 1
    writer = next(call for call in seen if call["model"] == "prov/writer")
    # the envelope shape: the Case input, then exactly the kept members' original texts (E4b Q7)
    assert writer["messages"][-1]["content"] == json.dumps(
        {
            "input": "what is 2 + 2?",
            "selected": [
                {"id": "member_1", "text": "alpha draft"},
                {"id": "member_3", "text": "gamma draft"},
            ],
        },
        separators=(",", ":"),
    )
    assert "beta draft" not in writer["messages"][-1]["content"]

    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("selection", "filter")
    assert combine["chosen"] == ["member_1", "member_3"]
    assert [member["score"] for member in combine["members"]] == [1.0, 0.0, 1.0]
    assert [member["signals"] for member in combine["members"]] == [
        {"score:judge": 9.0},
        {"score:judge": 4.0},
        {"score:judge": 7.0},
    ]
    assert combine["signal"] == {"key": "score:judge", "order": None}
    assert combine["judge"] is None
    assert combine["presentation_order"] == "author"

    assert operation(record, "op_judge_1")["output"] == (
        '{"member_1": 9, "member_2": 4, "member_3": 7}'
    )
    judge = next(call for call in seen if call["model"] == "prov/judge")
    assert judge["messages"][0]["role"] == "system"
    assert judge["messages"][0]["content"].startswith("judge-template@2 returns=scores")
    # WHY: the attribution param stays in the engine and never reaches the gateway
    assert all("binding" not in body for body in seen)
