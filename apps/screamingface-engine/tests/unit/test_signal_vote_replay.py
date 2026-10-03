"""A signal-weighted vote gives the same answer from a cache replay (OME-1289 E4a, SR#10).

FEATURE: ``sf.Vote(weights=sf.signal("cost_usd"))`` weighs each member by the cost of its own model
calls, found through the combine context ``sources``.
STORY: as a researcher, I rerun a cached run and the vote ends the same way, with the same weights,
although the cache hit costs nothing now.
INVARIANT: the signal comes from the call's original accounting (the cache reference), never from
the retained accounting of the replay.

The data file under ``data/combine_contract/`` is what the SDK compiles (the SDK drift guard keeps
it byte-equal), so this runs the real compiler output. The first run is a cache miss, the second a
hit. This is a CHAR test: it passes on its first run by design (units 1 and 3 deliver the behavior).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_CANDIDATE = (
    (Path(__file__).parent / "data" / "combine_contract" / "signal_vote_candidate.url4")
    .read_text(encoding="utf-8")
    .removesuffix("\n")
)
# request model -> (reply, cost in credits); every call has 10 + 4 tokens and 30 ms
_MODELS = {
    "prov/alpha": ("A", "0.004"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("B", "0.002"),
}


def _assert_cost_vote(record: dict[str, Any]) -> None:
    combine = operation(record, "op_synthesis_1")["combine"]
    assert operation(record, "op_synthesis_1")["output"] == "A"
    assert combine["signal"] == {"key": "cost_usd", "order": None}
    assert [member["signals"] for member in combine["members"]] == [
        {"cost_usd": 0.004},
        {"cost_usd": 0.001},
        {"cost_usd": 0.002},
    ]
    assert [member["weight"] for member in combine["members"]] == [0.004, 0.001, 0.002]
    # WHY lower case: the text normalizer folds the case of the group value; the output keeps it.
    tally = [(row["value"], row["score"], row["holders"]) for row in combine["tally"]]
    assert [(value, members) for value, _, members in tally] == [
        ("a", ["member_1"]),
        ("b", ["member_2", "member_3"]),
    ]
    assert [score for _, score, _ in tally] == pytest.approx([0.004, 0.003])
    assert combine["chosen"] == ["member_1"]
    assert combine["result"]["status"] == "answered"


@pytest.mark.asyncio
async def test_signal_reduce_replays_identically_from_cache() -> None:
    first = await run_candidate(_CANDIDATE, _MODELS, "miss")
    second = await run_candidate(_CANDIDATE, _MODELS, "hit")

    _assert_cost_vote(first)
    _assert_cost_vote(second)
    assert (
        operation(first, "op_synthesis_1")["combine"]
        == operation(second, "op_synthesis_1")["combine"]
    )
    # The retained accounting keeps its own truth (a hit costs nothing now), which proves the
    # signals above came from the cache reference and not from this run's accounting.
    miss_cost = operation(first, "op_model_1")["accounting"]["usage"]["cost_usd"]
    hit_cost = operation(second, "op_model_1")["accounting"]["usage"]["cost_usd"]
    assert hit_cost == "0"
    assert miss_cost != hit_cost
