"""SDK-written Candidates run in the engine world (OME-1289 E4a: 9S, 10S, 8S, SR#10).

FEATURE: the url4 files under ``data/combine_contract/`` are what the SDK compiles (the SDK drift
guard keeps them byte-equal), so each test runs the real compiler output through the mocked
gateway of ``_signal_world.run_candidate``. All four are CHAR tests: they pass on their first run
by design (units 1, 3, 8E and 10E deliver the behavior).
STORY: as a researcher, the engine enforces what the SDK wrote:
- ``sf.Pick(by_signal=sf.signal("cost_usd"), order="min")``: the cheapest member's own text is the
  answer, and a cached rerun picks the same member although the cache hit costs nothing now.
- ``sf.Vote(weights=sf.signal("cost_usd"))``: each member is weighed by the cost of its own model
  calls, and a cached rerun ends the vote the same way, with the same weights.
- ``sf.Filter(where=sf.signal("field:confidence") >= 0.6)``: only the members that pass reach the
  writer after it, with the Case input (E4b ans:Q7), and the report shows every member's pass mark
  (1.0 or 0.0).
- ``sf.Vote(weights=sf.signal("score:judge"), judge=sf.Judge(..., returns="scores"))``: the vote
  follows the judge's scores, not the head count (two members agree on 12, the judge trusts the one
  that says 7, and 7 wins).
INVARIANT defended: a signal comes from the call's original accounting (the cache reference), never
from the retained accounting of the replay; the writer never sees a dropped member's text; the
judge call is paid once and its ``binding`` param never reaches the gateway.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"


def _read(name: str) -> str:
    return (_DATA / name).read_text(encoding="utf-8").removesuffix("\n")


_ARGMAX = _read("argmax_cost_candidate.url4")
# WHY: without `sources` the engine finds no cost, and the case fails after the member calls
assert "sources:" in _ARGMAX
_SIGNAL_VOTE = _read("signal_vote_candidate.url4")
_FILTER = _read("filter_pipeline_candidate.url4")
_JUDGE_VOTE = _read("judge_vote_candidate.url4")

# request model -> (reply, cost in credits); the cheapest member is member_2
_ARGMAX_MODELS = {
    "prov/alpha": ("A", "0.004"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("C", "0.002"),
}
# every call has 10 + 4 tokens and 30 ms
_VOTE_MODELS = {
    "prov/alpha": ("A", "0.004"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("B", "0.002"),
}
# members 1 and 3 pass the 0.6 threshold
_FILTER_REPLIES = {
    "prov/alpha": '{"answer":"A","confidence":0.9}',
    "prov/beta": '{"answer":"B","confidence":0.2}',
    "prov/gamma": '{"answer":"C","confidence":0.7}',
    "prov/delta": '{"answer":"D","confidence":0.5}',
}
_FILTER_MODELS = {
    **{model: (reply, "0.001") for model, reply in _FILTER_REPLIES.items()},
    "prov/writer": ("final", "0.001"),
}
_JUDGE_ANSWERS = {
    "prov/alpha": "alpha says 12",
    "prov/beta": "beta says 7",
    "prov/gamma": "gamma says 12",
    "prov/judge": json.dumps({"member_1": 1, "member_2": 5, "member_3": 3}),
}
_JUDGE_MODELS = {model: (answer, "0.001") for model, answer in _JUDGE_ANSWERS.items()}
_JUDGE_PREFIX = "judge-template@2 returns=scores"


def _assert_cheapest_member(record: dict[str, Any]) -> None:
    synthesis = operation(record, "op_synthesis_1")
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
async def test_sdk_argmax_by_cost_runs_and_replays_from_cache() -> None:
    first = await run_candidate(_ARGMAX, _ARGMAX_MODELS, "miss")
    second = await run_candidate(_ARGMAX, _ARGMAX_MODELS, "hit")

    _assert_cheapest_member(first)
    _assert_cheapest_member(second)
    assert (
        operation(first, "op_synthesis_1")["combine"]
        == operation(second, "op_synthesis_1")["combine"]
    )
    # The retained accounting keeps its own truth (a hit costs nothing now), which proves the
    # costs above came from the cache reference and not from this run's accounting.
    miss_cost = operation(first, "op_model_2")["accounting"]["usage"]["cost_usd"]
    hit_cost = operation(second, "op_model_2")["accounting"]["usage"]["cost_usd"]
    assert hit_cost == "0"
    assert miss_cost != hit_cost


@pytest.mark.asyncio
async def test_signal_reduce_replays_identically_from_cache() -> None:
    first = await run_candidate(_SIGNAL_VOTE, _VOTE_MODELS, "miss")
    second = await run_candidate(_SIGNAL_VOTE, _VOTE_MODELS, "hit")

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


@pytest.mark.asyncio
async def test_filter_pipeline_writer_sees_the_input_and_kept_members() -> None:
    seen: list[dict[str, Any]] = []

    record = await run_candidate(_FILTER, _FILTER_MODELS, "miss", on_request=seen.append)

    assert record["status"] == "completed"
    assert record["output"] == "final"
    # four members and the writer: the filter itself calls no model
    assert sum(call["model"] == "prov/writer" for call in seen) == 1
    assert len(seen) == 5
    writer = next(call for call in seen if call["model"] == "prov/writer")
    envelope = writer["messages"][-1]["content"]
    # the envelope shape: the Case input, then exactly the kept members' original texts, in
    # author order (E4b ans:Q7)
    assert envelope == json.dumps(
        {
            "input": "what is 2 + 2?",
            "selected": [
                {"id": "member_1", "text": _FILTER_REPLIES["prov/alpha"]},
                {"id": "member_3", "text": _FILTER_REPLIES["prov/gamma"]},
            ],
        },
        separators=(",", ":"),
    )
    for dropped in ("prov/beta", "prov/delta"):
        assert _FILTER_REPLIES[dropped] not in envelope

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


@pytest.mark.asyncio
async def test_sdk_judge_weighted_vote_runs_in_the_engine_world() -> None:
    bodies: list[dict[str, Any]] = []

    record = await run_candidate(_JUDGE_VOTE, _JUDGE_MODELS, "miss", on_request=bodies.append)

    synthesis = operation(record, "op_synthesis_1")
    assert synthesis["output"] == "beta says 7"
    combine = synthesis["combine"]
    tally = [(row["value"], row["score"], row["holders"]) for row in combine["tally"]]
    assert tally == [("7", 5.0, ["member_2"]), ("12", 4.0, ["member_1", "member_3"])]
    assert [member["signals"] for member in combine["members"]] == [
        {"score:judge": 1.0},
        {"score:judge": 5.0},
        {"score:judge": 3.0},
    ]
    assert [member["weight"] for member in combine["members"]] == [1.0, 5.0, 3.0]
    assert combine["signal"] == {"key": "score:judge", "order": None}
    assert combine["judge"] is None
    assert combine["presentation_order"] == "author"
    assert combine["chosen"] == ["member_2"]
    assert operation(record, "op_judge_1")["output"] == _JUDGE_ANSWERS["prov/judge"]
    # one judge call, and the attribution param never reaches the gateway
    judge_calls = [body for body in bodies if body["model"] == "prov/judge"]
    assert len(judge_calls) == 1
    assert all("binding" not in body for body in bodies)
    system = judge_calls[0]["messages"][0]
    assert system["role"] == "system"
    # WHY U+2028: url4 carries a newline of the intent text as a line separator
    assert system["content"].startswith(f"{_JUDGE_PREFIX} You are a judge.")
