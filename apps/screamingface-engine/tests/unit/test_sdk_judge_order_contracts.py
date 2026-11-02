"""SDK-compiled judge-order candidate runs in the engine world (E4b unit 5, JO#9 and JO#12).

FEATURE: judge-order — an SDK judge with order="min" runs end to end and returns the lowest
member's original text.
STORY: as a benchmark author, I want the judge to score each answer where a lower score is better,
and the answer to be the member with the lowest score.
INVARIANT: a tie at the lowest score goes to the first member in author order.
INVARIANT: the judge is told that a lower number is better, in one judge call.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"
_FIXTURE = "judge_order_min_candidate.url4"
_TEXTS = {
    "prov/alpha": "alpha: three errors",
    "prov/beta": "beta: no errors",
    "prov/gamma": "gamma: one error",
}


def _candidate() -> str:
    # WHY in a function: a missing fixture fails the test, not the collection.
    return (_DATA / _FIXTURE).read_text(encoding="utf-8").removesuffix("\n")


def _models(judge_reply: dict[str, int]) -> dict[str, tuple[str, str]]:
    return {
        **{model: (text, "0.001") for model, text in _TEXTS.items()},
        "prov/judge": (json.dumps(judge_reply), "0.001"),
    }


@pytest.mark.asyncio
async def test_judge_order_min_tie_goes_to_the_first_member() -> None:
    # JO-D3 (M x M): min(2, 1, 1) = 1 is held by member_2 and member_3; the first in author order
    # wins.
    record = await run_candidate(
        _candidate(), _models({"member_1": 2, "member_2": 1, "member_3": 1}), "miss"
    )

    synthesis = operation(record, "op_synthesis_1")
    assert synthesis["output"] == "beta: no errors"
    assert synthesis["combine"]["chosen"] == ["member_2"]
    assert synthesis["combine"]["tie"] is True


@pytest.mark.asyncio
async def test_engine_runs_sdk_judge_order_min_and_returns_the_lowest_member_text() -> None:
    # JO-1 and JO-4: the lowest score wins, the evidence is complete, one judge call, and the
    # judge is told that a lower number is better.
    bodies: list[dict[str, Any]] = []
    reply = {"member_1": 3, "member_2": 0, "member_3": 1}

    record = await run_candidate(_candidate(), _models(reply), "miss", on_request=bodies.append)

    # oracle by hand: min(3, 0, 1) = 0 -> member_2 -> "beta: no errors"; no tie
    synthesis = operation(record, "op_synthesis_1")
    assert synthesis["output"] == "beta: no errors"
    combine = synthesis["combine"]
    assert (combine["kind"], combine["reducer"]) == ("answer", "judge")
    assert combine["chosen"] == ["member_2"]
    assert combine["tie"] is False
    assert combine["judge"] == {
        "raw": json.dumps(reply),
        "returns": "scores",
        "parsed": {"member_1": 3.0, "member_2": 0.0, "member_3": 1.0},
    }
    assert [member["score"] for member in combine["members"]] == [3.0, 0.0, 1.0]
    assert combine["presentation_order"] == "author"
    assert combine["result"]["member_id"] == "member_2"
    assert combine["result"]["status"] == "answered"
    judge_calls = [body for body in bodies if body["model"] == "prov/judge"]
    assert len(judge_calls) == 1
    system = judge_calls[0]["messages"][0]
    assert system["role"] == "system"
    # WHY U+2028: url4 carries a newline of the intent text as a line separator; see
    # test_sdk_candidate_contracts.py.
    assert system["content"].startswith(
        "judge-template@1 returns=scores order=min You are a judge."
    )
    assert "A lower number means a better answer." in system["content"]
