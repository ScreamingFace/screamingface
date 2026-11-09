"""A rank recipe that the SDK compiled writes the rank and the cut in its run record (E4b part 2).

FEATURE: ``recipe_s10.url4`` is ``sf.Rank(k=2, by=sf.Judge(...))`` then a writer, as the SDK
compiles it (the SDK drift guard keeps the bytes). Run in the engine world with a mocked gateway,
its combine operation writes each member's rank and the cut ``{"k": 2, "order": "max"}``: the SDK
writes no ``order`` for a judge rank, so the engine fills in the default.
STORY: as a researcher, the report of a real rank run shows how far each dropped draft was from
the cut.
INVARIANT defended: the url4 file does not change (ans:Q4); only the evidence gains the keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"
_WRITER = "provider/writer"
_JUDGE = "provider/judge"
_DRAFTS = {
    "provider/alpha": "alpha draft",
    "provider/beta": "beta draft",
    "provider/gamma": "gamma draft",
}
# Judge scores 2, 9, 5: member_2 (9) first, member_3 (5), member_1 (2). So the ranks are 3, 1, 2.
_JUDGE_SCORES = '{"member_1": 2, "member_2": 9, "member_3": 5}'


def _models(replies: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    return {route: (reply, "0.001") for route, reply in replies.items()}


@pytest.mark.asyncio
async def test_sdk_rank_recipe_run_writes_rank_and_cut() -> None:
    recipe = (_DATA / "recipe_s10.url4").read_text(encoding="utf-8").removesuffix("\n")

    record = await run_candidate(
        recipe, _models({**_DRAFTS, _JUDGE: _JUDGE_SCORES, _WRITER: "final answer"}), "miss"
    )

    assert record["status"] == "completed"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2", "member_3"]
    assert [member.get("rank") for member in combine["members"]] == [3, 1, 2]
    assert combine["cut"] == {"k": 2, "order": "max"}
