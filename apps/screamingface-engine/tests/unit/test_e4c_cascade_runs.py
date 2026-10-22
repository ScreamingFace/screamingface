"""sf.Cascade runs on the Engine world: cheap first, escalate only when the signal is weak.

FEATURE: E4c (OME-1291) cascade rows CA#2 - #6, #10, #11, #11a, #12, #13, #25; branch-core
BC#6a, #6b, #10; gate GT#19 - #21 (panel gate with a recipe otherwise).
STORY: as a researcher whose result is a saving, a Case that passes stage 1 pays stage 1 only; a
stage that fails or abstains escalates; the last tier can be a scored decline.
The url4 files are the SDK compile (``packages/screamingface/tests/test_e4c_gate_fixtures.py``).
"""

from __future__ import annotations

from typing import Any

import pytest
from _gate_world import FAIL, Gateway, fixture, operations, run_gate

from url4.core.errors import ResolutionError

_STAGE_ONE = ("prov/a", "prov/b")
_STAGE_TWO = ("prov/c", "prov/d")


def _replies(one: tuple[str, str], two: tuple[str, str], large: str = "L") -> dict[str, Any]:
    return {
        **dict(zip(_STAGE_ONE, one, strict=True)),
        **dict(zip(_STAGE_TWO, two, strict=True)),
        "prov/large": large,
    }


def _user_text(request: dict[str, Any]) -> str:
    return next(m["content"] for m in reversed(request["messages"]) if m["role"] == "user")


@pytest.mark.asyncio
async def test_stage_one_passes_and_later_stages_make_zero_calls() -> None:
    # CA#2
    gateway = Gateway(_replies(("A", "A"), ("C", "C")))
    record = await run_gate(fixture("cascade_three.url4"), gateway, "a question")

    assert record["output"] == "A"
    assert sorted(request["model"] for request in gateway.seen) == list(_STAGE_ONE)
    outer = operations(record)["op_gate_1"]["decision"]
    assert outer["branch"] == "then"
    assert outer["not_run"][0]["branch"] == "otherwise"


@pytest.mark.asyncio
async def test_escalated_stage_reads_the_case_input_not_the_previous_answer() -> None:
    # CA#3 / BC-5: stage 2 and the large model answer the original question.
    gateway = Gateway(_replies(("A", "B"), ("C", "D")))
    record = await run_gate(fixture("cascade_three.url4"), gateway, "the question")

    assert record["output"] == "L"
    later = [r for r in gateway.seen if r["model"] in (*_STAGE_TWO, "prov/large")]
    assert len(later) == 3
    assert {_user_text(request) for request in later} == {"the question"}


@pytest.mark.asyncio
async def test_failed_gated_stage_escalates_instead_of_failing_the_case() -> None:
    # CA#4 / CA-6: every stage-1 member fails; the panel does not fail (quorum 0), no voters,
    # the null branch escalates to stage 2.
    gateway = Gateway(_replies((FAIL, FAIL), ("C", "C")))
    record = await run_gate(fixture("cascade_three.url4"), gateway)

    assert record["status"] == "completed"
    assert record["output"] == "C"
    outer = operations(record)["op_gate_1"]["decision"]
    assert outer["panel"]["branch"] is None
    assert outer["branch"] == "otherwise"


@pytest.mark.asyncio
async def test_abstained_gated_stage_escalates() -> None:
    # CA#5 / CA-7: both stage-1 members give an empty answer, so the vote abstains no_votes.
    gateway = Gateway(_replies((" ", " "), ("C", "C")))
    record = await run_gate(fixture("cascade_three.url4"), gateway)
    assert record["output"] == "C"


@pytest.mark.asyncio
async def test_partially_failed_stage_decides_on_the_members_that_answered() -> None:
    # CA#6 / CA-29 (ans:Q24): one member fails, the other answers: agreement over one vote is 1.0.
    gateway = Gateway(_replies(("A", FAIL), ("C", "C")))
    record = await run_gate(fixture("cascade_three.url4"), gateway)

    assert record["output"] == "A"
    assert all(request["model"] in _STAGE_ONE for request in gateway.seen)


@pytest.mark.asyncio
async def test_every_stage_escalates_and_the_case_abstains_gate_not_met() -> None:
    # CA#10 / CA-9 / CA-20 / BC#6a: the innermost word abstains; the root JOIN copies it.
    gateway = Gateway(_replies(("A", "B"), ("C", "D")))
    record = await run_gate(fixture("cascade_abstain.url4"), gateway)

    assert record["output"] == ""
    assert record.get("abstained") is True
    root = operations(record)["op_gate_1"]["decision"]
    assert root["result"] == {"status": "abstain", "reason": "gate_not_met"}
    assert len(gateway.seen) == 4  # every stage ran once


@pytest.mark.asyncio
async def test_every_stage_fails_and_the_last_failure_fails_the_case() -> None:
    # CA#11 / CA-19: stages before the last escalate; the last (required) stage's failure fails.
    gateway = Gateway(_replies((FAIL, FAIL), (FAIL, FAIL), large=FAIL))
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("cascade_three.url4"), gateway)
    assert caught.value.code == "aigateway_http_400"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "abstained", "code"),
    [("cascade_abstain.url4", True, None), ("cascade_fail_closed.url4", False, "fail_closed")],
)
async def test_gated_last_stage_with_no_voters_follows_the_otherwise_word(
    name, abstained, code
) -> None:
    # CA#11a / CA-30: the last stage's members all fail: abstain no_votes, or fail_closed.
    gateway = Gateway(_replies((FAIL, FAIL), (FAIL, FAIL)))
    if code is None:
        record = await run_gate(fixture(name), gateway)
        assert record.get("abstained") is abstained
        root = operations(record)["op_gate_1"]["decision"]
        assert root["result"] == {"status": "abstain", "reason": "no_votes"}
        return
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture(name), gateway)
    assert caught.value.code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("replies", "output", "models"),
    [
        ({"prov/a": "A", "prov/b": "B", "prov/c": "C"}, "A", ["prov/a"]),
        ({"prov/a": FAIL, "prov/b": "B", "prov/c": "C"}, "B", ["prov/a", "prov/b"]),
        ({"prov/a": " ", "prov/b": FAIL, "prov/c": "C"}, "C", ["prov/a", "prov/b", "prov/c"]),
    ],
)
async def test_first_success_returns_the_first_answer_verbatim(replies, output, models) -> None:
    # CA#12 / CA-10 (OME-1465 sequential)
    answer = {**replies}
    if output == "A":
        answer["prov/a"] = "A line one\nA"
        output = "A line one\nA"
    gateway = Gateway(answer)
    record = await run_gate(fixture("first_success.url4"), gateway)

    assert record["output"] == output
    assert [request["model"] for request in gateway.seen] == models


@pytest.mark.asyncio
@pytest.mark.parametrize(("agree", "calls"), [(True, 2), (False, 7)])
async def test_adaptive_sampling_pays_two_or_two_plus_five(agree: bool, calls: int) -> None:
    # CA#13 / CA-11 (ans:Q7): no sample reuse; an escalated Case pays 2 + 5.
    def reply(request: dict[str, Any]) -> str:
        seed = request.get("seed", 0)
        return "A" if agree or seed >= 2 else ("A" if seed == 0 else "B")

    gateway = Gateway({"prov/m": reply})
    record = await run_gate(fixture("adaptive_sampling.url4"), gateway)

    assert gateway.calls("prov/m") == calls
    assert record["output"] == "A"


@pytest.mark.asyncio
async def test_cascade_then_writer_reads_the_final_answer() -> None:
    # CA#25 / CA-26
    gateway = Gateway({"prov/a": "A", "prov/b": "B", "prov/large": "L", "prov/writer": "W"})
    record = await run_gate(fixture("cascade_then_writer.url4"), gateway, "q")

    assert record["output"] == "W"
    writer = next(request for request in gateway.seen if request["model"] == "prov/writer")
    assert _user_text(writer) == "L"


@pytest.mark.asyncio
async def test_recipe_body_ending_in_an_abstaining_vote_marks_the_case_abstained() -> None:
    # BC#6b / BC-37: the then body is a block whose vote abstains (no voters).
    gateway = Gateway({"prov/a": " ", "prov/b": " ", "prov/general": "G"})
    record = await run_gate(fixture("vote_body_gate.url4"), gateway, "an integral")

    assert record.get("abstained") is True
    result = operations(record)["op_gate_1"]["decision"]["result"]
    assert result == {"status": "abstain", "reason": "no_votes"}


@pytest.mark.asyncio
async def test_decide_runs_after_a_delayed_decision_call_and_members() -> None:
    # BC#10 / BC-31 (D10): members reply late; DECIDE still reads the decision call's record.
    gateway = Gateway(
        {"prov/alpha": "A", "prov/beta": "B", "prov/gamma": "C", "prov/large": "L"},
        delays={"prov/alpha": 0.2, "prov/beta": 0.1},
    )
    record = await run_gate(fixture("panel_escalates.url4"), gateway)

    assert record["output"] == "L"  # GT#19 - #21: the panel splits, the large model answers
    decision = operations(record)["op_gate_1"]["decision"]
    assert decision["panel"] == {"operation_id": "op_synthesis_1", "branch": "fallback"}
    large = next(request for request in gateway.seen if request["model"] == "prov/large")
    assert _user_text(large) == "what is 2 + 2?"
