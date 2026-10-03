"""An SDK-written filter-then-model Pipeline runs in the engine world (OME-1289, unit 10S, FL#8).

FEATURE: ``sf.Filter(where=sf.signal("field:confidence") >= 0.6)`` keeps the members that pass, and
the writer after it sees exactly those members' own texts as the selection envelope.
STORY: as a researcher, "only the confident drafts reach the writer" is enforced by the engine, and
the report shows every member's pass mark (1.0 or 0.0) next to the kept ids.
INVARIANT defended: the writer never sees a dropped member's text, and the evidence carries the
confidence each member was judged by (the signal key, no order).

The data file under ``data/combine_contract/`` is what the SDK compiles (the SDK drift guard keeps
it byte-equal), so this runs the real compiler output. This is a CHAR test: it passes on its first
run by design (units 1, 3 and 10E deliver the behavior). The world runner is
``_signal_world.run_candidate``; the test records the gateway requests by wrapping its handler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_CANDIDATE = (
    (Path(__file__).parent / "data" / "combine_contract" / "filter_pipeline_candidate.url4")
    .read_text(encoding="utf-8")
    .removesuffix("\n")
)
# request model -> (reply, cost in credits); members 1 and 3 pass the 0.6 threshold
_REPLIES = {
    "prov/alpha": '{"answer":"A","confidence":0.9}',
    "prov/beta": '{"answer":"B","confidence":0.2}',
    "prov/gamma": '{"answer":"C","confidence":0.7}',
    "prov/delta": '{"answer":"D","confidence":0.5}',
}
_MODELS = {
    **{model: (reply, "0.001") for model, reply in _REPLIES.items()},
    "prov/writer": ("final", "0.001"),
}


@pytest.mark.asyncio
async def test_sdk_filter_pipeline_runs_and_the_writer_sees_only_the_kept_members() -> None:
    seen: list[dict[str, Any]] = []

    record = await run_candidate(_CANDIDATE, _MODELS, "miss", on_request=seen.append)

    assert record["status"] == "completed"
    assert record["output"] == "final"
    # four members and the writer: the filter itself calls no model
    assert sum(call["model"] == "prov/writer" for call in seen) == 1
    assert len(seen) == 5
    writer = next(call for call in seen if call["model"] == "prov/writer")
    envelope = writer["messages"][-1]["content"]
    # the envelope shape: exactly the kept members' original texts, in author order
    assert envelope == json.dumps(
        {
            "selected": [
                {"id": "member_1", "text": _REPLIES["prov/alpha"]},
                {"id": "member_3", "text": _REPLIES["prov/gamma"]},
            ]
        },
        separators=(",", ":"),
    )
    for dropped in ("prov/beta", "prov/delta"):
        assert _REPLIES[dropped] not in envelope

    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("selection", "filter")
    assert combine["chosen"] == ["member_1", "member_3"]
    # 10E F6: a voter's pass mark is 1.0 (kept) or 0.0 (dropped)
    assert [member["score"] for member in combine["members"]] == [1.0, 0.0, 1.0, 0.0]
    assert combine["signal"] == {"key": "field:confidence", "order": None}
    assert [member["signals"] for member in combine["members"]] == [
        {"field:confidence": 0.9},
        {"field:confidence": 0.2},
        {"field:confidence": 0.7},
        {"field:confidence": 0.5},
    ]
