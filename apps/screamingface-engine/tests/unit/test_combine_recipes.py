"""The combine recipes run offline end to end in the Engine world (E4b recipes PRD, RC#1-11).

FEATURE: each ``combine_contract/recipe_*.url4`` is what the SDK compiles for one README recipe
(the SDK drift guard keeps it byte-equal). Each test runs those bytes through the mocked gateway
of ``_signal_world.run_candidate`` and checks the final answer that the PRD states.
STORY: as a benchmark author, I copy a recipe and trust that it runs: the median number, the
member nearest the median, the most confident member, the top-N or the members above a threshold
and then a writer, a judge's top-N and then a writer, and the judge's best member.
INVARIANT defended: the writer after a Rank or Filter gets the Case input and only the kept
member texts (contracts C2); a Filter `>` is strict; a judge reply that is not strict scores fails
the Case and is not retried; a member with no JSON value is never picked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

from url4.core.errors import ResolutionError

_DATA = Path(__file__).parent / "data" / "combine_contract"
# The Case input that run_candidate links (test_samples_seed_contract.py:77).
_CASE_INPUT = "what is 2 + 2?"
_WRITER = "provider/writer"
_JUDGE = "provider/judge"
_FINAL = "final answer"
_DRAFTS = {
    "provider/alpha": "alpha draft",
    "provider/beta": "beta draft",
    "provider/gamma": "gamma draft",
}
# RC-7: best first is member_2 (9), then member_3 (5); member_1 (2) is cut.
_JUDGE_SCORES = '{"member_1": 2, "member_2": 9, "member_3": 5}'


def _recipe(name: str) -> str:
    # WHY read here and not at import: a missing fixture must fail the test (RED), not the import.
    path = _DATA / name
    assert path.exists(), f"combine_contract/{name} is missing - write it with the SDK"
    return path.read_text(encoding="utf-8").removesuffix("\n")


def _models(replies: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    return {route: (reply, "0.001") for route, reply in replies.items()}


def _envelope(*kept: tuple[str, str]) -> str:
    """The selection envelope of contracts C2: the Case input and the kept texts, canonical JSON."""
    selected = [{"id": member, "text": text} for member, text in kept]
    return json.dumps(
        {"input": _CASE_INPUT, "selected": selected},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _writer_messages(seen: list[dict[str, Any]]) -> list[str]:
    """The user message of every writer call, in call order."""
    return [call["messages"][-1]["content"] for call in seen if call["model"] == _WRITER]


@pytest.mark.asyncio
async def test_recipe_s10_rank_by_judge_then_writer_runs_end_to_end() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _recipe("recipe_s10.url4"),
        _models({**_DRAFTS, _JUDGE: _JUDGE_SCORES, _WRITER: _FINAL}),
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    assert record["output"] == "final answer"
    assert _writer_messages(seen) == [
        '{"input":"what is 2 + 2?","selected":[{"id":"member_2","text":"beta draft"},'
        '{"id":"member_3","text":"gamma draft"}]}'
    ]
    assert sum(call["model"] == _JUDGE for call in seen) == 1
    assert len(seen) == 5
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("selection", "rank")
    assert combine["chosen"] == ["member_2", "member_3"]
    assert [m["score"] for m in combine["members"]] == [2.0, 9.0, 5.0]


@pytest.mark.asyncio
async def test_recipe_s9_filter_confidence_then_writer_runs_end_to_end() -> None:
    alpha = '{"answer":"A","confidence":0.7}'
    beta = '{"answer":"B","confidence":0.71}'
    gamma = '{"answer":"C","confidence":0.9}'
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _recipe("recipe_s9.url4"),
        _models(
            {
                "provider/alpha": alpha,
                "provider/beta": beta,
                "provider/gamma": gamma,
                _WRITER: _FINAL,
            }
        ),
        "miss",
        on_request=seen.append,
    )

    assert record["output"] == "final answer"
    assert _writer_messages(seen) == [_envelope(("member_2", beta), ("member_3", gamma))]
    assert alpha not in _writer_messages(seen)[0]
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2", "member_3"]
    assert [m["score"] for m in combine["members"]] == [0.0, 1.0, 1.0]
    assert [m["signals"] for m in combine["members"]] == [
        {"field:confidence": 0.7},
        {"field:confidence": 0.71},
        {"field:confidence": 0.9},
    ]


@pytest.mark.asyncio
async def test_recipe_s7_rank_by_field_then_writer_runs_end_to_end() -> None:
    alpha = '{"answer":"A","confidence":0.5}'
    beta = '{"answer":"B","confidence":0.3}'
    gamma = '{"answer":"C","confidence":0.9}'
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _recipe("recipe_s7.url4"),
        _models(
            {
                "provider/alpha": alpha,
                "provider/beta": beta,
                "provider/gamma": gamma,
                _WRITER: _FINAL,
            }
        ),
        "miss",
        on_request=seen.append,
    )

    assert record["output"] == "final answer"
    assert _writer_messages(seen) == [_envelope(("member_3", gamma), ("member_1", alpha))]
    assert beta not in _writer_messages(seen)[0]
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("selection", "rank")
    assert combine["chosen"] == ["member_3", "member_1"]
    assert [m["score"] for m in combine["members"]] == [0.5, 0.3, 0.9]


@pytest.mark.asyncio
async def test_recipe_s9_with_no_pass_abstains() -> None:
    alpha = '{"answer":"A","confidence":0.7}'
    beta = '{"answer":"B","confidence":0.2}'
    gamma = '{"answer":"C","confidence":0.5}'
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _recipe("recipe_s9.url4"),
        _models(
            {
                "provider/alpha": alpha,
                "provider/beta": beta,
                "provider/gamma": gamma,
                _WRITER: _FINAL,
            }
        ),
        "miss",
        on_request=seen.append,
    )

    synthesis = operation(record, "op_synthesis_1")
    assert synthesis["output"] == ""
    assert synthesis["combine"]["result"]["status"] == "abstain"
    assert synthesis["combine"]["result"]["reason"] == "no_votes"
    assert synthesis["combine"]["chosen"] == []
    assert _writer_messages(seen) == [""]
    assert not record.get("abstained", False)
    assert record["output"] == "final answer"


@pytest.mark.asyncio
async def test_recipe_s10_with_invalid_judge_reply_fails_permanently() -> None:
    seen: list[dict[str, Any]] = []
    with pytest.raises(ResolutionError) as caught:
        await run_candidate(
            _recipe("recipe_s10.url4"),
            _models({**_DRAFTS, _JUDGE: "member 2 is best", _WRITER: _FINAL}),
            "miss",
            on_request=seen.append,
        )

    assert caught.value.code == "judge_reply_invalid"
    assert caught.value.permanent is True
    assert sum(call["model"] == _JUDGE for call in seen) == 1
    assert _writer_messages(seen) == []


@pytest.mark.asyncio
async def test_recipe_s11_judge_argmax_returns_the_best_member_text() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _recipe("recipe_s11_max.url4"),
        _models({**_DRAFTS, _JUDGE: _JUDGE_SCORES}),
        "miss",
        on_request=seen.append,
    )

    assert record["output"] == "beta draft"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("answer", "judge")
    assert combine["chosen"] == ["member_2"]
    assert combine["result"]["member_id"] == "member_2"
    assert sum(call["model"] == _JUDGE for call in seen) == 1


@pytest.mark.asyncio
async def test_recipe_s8_pick_by_field_signal_max_runs_end_to_end() -> None:
    alpha = '{"answer":"A","confidence":0.3}'
    beta = '{"answer":"B","confidence":0.9}'
    gamma = '{"answer":"C","confidence":0.5}'
    record = await run_candidate(
        _recipe("recipe_s8.url4"),
        _models({"provider/alpha": alpha, "provider/beta": beta, "provider/gamma": gamma}),
        "miss",
    )

    assert record["output"] == beta
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2"]
    assert combine["signal"] == {"key": "field:confidence", "order": "max"}
    assert [m["signals"] for m in combine["members"]] == [
        {"field:confidence": 0.3},
        {"field:confidence": 0.9},
        {"field:confidence": 0.5},
    ]


@pytest.mark.asyncio
async def test_recipe_s5_pick_confidence_max_runs_end_to_end() -> None:
    alpha = '{"answer":"A","confidence":0.3}'
    beta = '{"answer":"B","confidence":0.9}'
    gamma = '{"answer":"C","confidence":0.5}'
    record = await run_candidate(
        _recipe("recipe_s5.url4"),
        _models({"provider/alpha": alpha, "provider/beta": beta, "provider/gamma": gamma}),
        "miss",
    )

    assert record["output"] == beta
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("answer", "pick")
    assert combine["chosen"] == ["member_2"]
    assert combine["result"]["member_id"] == "member_2"


@pytest.mark.asyncio
async def test_recipe_s5_plain_text_member_is_not_picked() -> None:
    alpha = "I am sure: 0.99"
    beta = '{"answer":"B","confidence":0.4}'
    gamma = '{"answer":"C","confidence":0.2}'
    record = await run_candidate(
        _recipe("recipe_s5.url4"),
        _models({"provider/alpha": alpha, "provider/beta": beta, "provider/gamma": gamma}),
        "miss",
    )

    assert record["output"] == beta
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2"]
    assert combine["members"][0]["status"] == "fail"
    assert combine["members"][0]["reason"] == "not_json"


@pytest.mark.asyncio
async def test_recipe_s5_with_no_json_member_abstains() -> None:
    record = await run_candidate(
        _recipe("recipe_s5.url4"),
        _models(
            {
                "provider/alpha": "alpha says four",
                "provider/beta": "beta says four",
                "provider/gamma": "gamma says four",
            }
        ),
        "miss",
    )

    assert record["abstained"] is True
    assert record["output"] == ""
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["result"]["status"] == "abstain"
    assert combine["result"]["reason"] == "no_votes"


@pytest.mark.asyncio
async def test_recipe_s1_median_value_runs_end_to_end() -> None:
    record = await run_candidate(
        _recipe("recipe_s1.url4"),
        _models(
            {
                "provider/alpha": "alpha thinks 10",
                "provider/beta": "beta thinks 20",
                "provider/gamma": "gamma thinks 90",
            }
        ),
        "miss",
    )

    assert record["output"] == "20"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["median"] == "20"
    assert combine["result"]["value"] == "20"
    assert combine["result"]["member_id"] is None


@pytest.mark.asyncio
async def test_recipe_s2_median_nearest_runs_end_to_end() -> None:
    record = await run_candidate(
        _recipe("recipe_s2.url4"),
        _models(
            {
                "provider/alpha": "alpha thinks 10",
                "provider/beta": "beta thinks 20",
                "provider/gamma": "gamma thinks 90",
            }
        ),
        "miss",
    )

    assert record["output"] == "beta thinks 20"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["chosen"] == ["member_2"]
    assert combine["result"]["member_id"] == "member_2"


@pytest.mark.asyncio
async def test_engine_runs_sdk_mean_with_static_weights() -> None:
    # Oracle: (10*1 + 20*1 + 60*2) / (1 + 1 + 2) = 37.5 (E4b S3, MN#22).
    record = await run_candidate(
        _recipe("recipe_s3.url4"),
        _models(
            {
                "provider/alpha": "x = 10",
                "provider/beta": "x = 20",
                "provider/gamma": "x = 60",
            }
        ),
        "miss",
    )

    assert record["status"] == "completed"
    assert operation(record, "op_synthesis_1")["output"] == "37.5"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["reducer"] == "mean"
    assert combine["mean"] == "37.5"
    assert combine["median"] is None
    assert [m["weight"] for m in combine["members"]] == [1.0, 1.0, 2.0]
    assert combine["operators"] == ["last_number@1", "numeric@1", "weighted_mean@1", "value@1"]


@pytest.mark.asyncio
async def test_engine_runs_mean_block_weighted_by_field_confidence() -> None:
    # Oracle: (0.2*10 + 0.8*20) / (0.2 + 0.8) = 18; gamma has weight 0, so it is dropped (ans:Q2).
    record = await run_candidate(
        _recipe("recipe_s4.url4"),
        _models(
            {
                "provider/alpha": '{"answer": 10, "confidence": 0.2}',
                "provider/beta": '{"answer": 20, "confidence": 0.8}',
                "provider/gamma": '{"answer": 99, "confidence": 0}',
            }
        ),
        "miss",
    )

    assert record["status"] == "completed"
    assert operation(record, "op_synthesis_1")["output"] == "18"
    combine = operation(record, "op_synthesis_1")["combine"]
    assert combine["mean"] == "18"
    assert [m["weight"] for m in combine["members"]] == [0.2, 0.8, None]
    assert [m["signals"] for m in combine["members"]] == [
        {"field:confidence": 0.2},
        {"field:confidence": 0.8},
        {"field:confidence": 0.0},
    ]
    assert combine["signal"] == {"key": "field:confidence", "order": None}
    assert combine["operators"] == ["json_field@1", "numeric@1", "weighted_mean@1", "value@1"]
