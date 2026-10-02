"""An SDK-written argmax-by-cost Fusion runs in the engine world and replays (OME-1289, 9S).

FEATURE: ``sf.Pick(by_signal=sf.signal("cost_usd"), order="min")`` weighs no vote: the cheapest
member's own text is the answer, found through the combine context ``sources``.
STORY: as a researcher, "the cheapest member's answer" is enforced by the engine, and a cached rerun
picks the same member with the same costs, although the cache hit costs nothing now.
INVARIANT defended: the pick follows the cost of the call's original accounting (the cache
reference), never the retained accounting of the replay, so both runs give the same evidence.

The data file under ``data/combine_contract/`` is what the SDK compiles (the SDK drift guard keeps
it byte-equal), so this runs the real compiler output. The first run is a cache miss, the second a
hit. This is a CHAR test: it passes on its first run by design (units 1, 3 and 10E deliver the
behavior). The world runner is ``_signal_world.run_candidate``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _signal_world import run_candidate
from test_signal_vote_replay import _operation

_CANDIDATE = (
    (Path(__file__).parent / "data" / "combine_contract" / "argmax_cost_candidate.url4")
    .read_text(encoding="utf-8")
    .removesuffix("\n")
)
# WHY: without `sources` the engine finds no cost, and the case fails after the member calls
assert "sources:" in _CANDIDATE
# request model -> (reply, cost in credits); the cheapest member is member_2
_MODELS = {
    "prov/alpha": ("A", "0.004"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("C", "0.002"),
}


def _assert_cheapest_member(record: dict[str, Any]) -> None:
    synthesis = _operation(record, "op_synthesis_1")
    combine = synthesis["combine"]
    assert synthesis["output"] == "B"
    assert (combine["kind"], combine["reducer"]) == ("answer", "pick")
    assert combine["chosen"] == ["member_2"]
    assert combine["result"]["member_id"] == "member_2"
    assert combine["result"]["status"] == "answered"
    # the order the SDK wrote in both steps is the one the evidence reports (10E F3)
    assert combine["signal"] == {"key": "cost_usd", "order": "min"}
    assert [member["signals"] for member in combine["members"]] == [
        {"cost_usd": 0.004},
        {"cost_usd": 0.001},
        {"cost_usd": 0.002},
    ]


@pytest.mark.asyncio
async def test_sdk_argmax_by_cost_runs_and_replays_from_cache() -> None:
    first = await run_candidate(_CANDIDATE, _MODELS, "miss")
    second = await run_candidate(_CANDIDATE, _MODELS, "hit")

    _assert_cheapest_member(first)
    _assert_cheapest_member(second)
    assert (
        _operation(first, "op_synthesis_1")["combine"]
        == _operation(second, "op_synthesis_1")["combine"]
    )
    # The retained accounting keeps its own truth (a hit costs nothing now), which proves the
    # costs above came from the cache reference and not from this run's accounting.
    miss_cost = _operation(first, "op_model_2")["accounting"]["usage"]["cost_usd"]
    hit_cost = _operation(second, "op_model_2")["accounting"]["usage"]["cost_usd"]
    assert hit_cost == "0"
    assert miss_cost != hit_cost
