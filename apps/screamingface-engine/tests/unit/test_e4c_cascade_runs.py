"""sf.Cascade runs on the Engine world: cheap first, escalate only when the signal is weak.

FEATURE: E4c (OME-1291) cascade rows CA#2 - #6, #10, #11, #11a, #12, #13, #25; branch-core
BC#6a, #6b, #10; gate GT#19 - #21 (panel gate with a recipe otherwise).
STORY: as a researcher whose result is a saving, a Case that passes tier 1 pays tier 1 only;
only a sf.escalate_if line escalates (2026-11-12): a tier that fails fails the Case, a tier that
abstains makes it abstain, a missing number fails it with signal_missing; the last tier can be a
scored decline.
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
async def test_tier_one_passes_and_later_tiers_make_zero_calls() -> None:
    # CA#2
    gateway = Gateway(_replies(("A", "A"), ("C", "C")))
    record = await run_gate(fixture("cascade_three.url4"), gateway, "a question")

    assert record["output"] == "A"
    assert sorted(request["model"] for request in gateway.seen) == list(_STAGE_ONE)
    outer = operations(record)["op_gate_1"]["decision"]
    assert outer["branch"] == "then"
    assert outer["not_run"][0]["branch"] == "otherwise"


@pytest.mark.asyncio
async def test_escalated_tier_reads_the_case_input_not_the_previous_answer() -> None:
    # CA#3 / BC-5: tier 2 and the large model answer the original question.
    gateway = Gateway(_replies(("A", "B"), ("C", "D")))
    record = await run_gate(fixture("cascade_three.url4"), gateway, "the question")

    assert record["output"] == "L"
    later = [r for r in gateway.seen if r["model"] in (*_STAGE_TWO, "prov/large")]
    assert len(later) == 3
    assert {_user_text(request) for request in later} == {"the question"}


@pytest.mark.asyncio
@pytest.mark.parametrize("one", [(FAIL, FAIL), ("A", FAIL)], ids=["every_member", "one_member"])
async def test_failed_tier_fails_the_case_and_does_not_escalate(one: tuple[str, str]) -> None:
    # CA#4, CA#6 (2026-11-12, reverses ans:Q17/Q24): a condition line keeps the author's Fanout;
    # its quorum ('all') fails the tier, and only a line escalates.
    gateway = Gateway(_replies(one, ("C", "C")))
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("cascade_three.url4"), gateway)

    assert caught.value.code == "aigateway_http_400"
    assert all(request["model"] in _STAGE_ONE for request in gateway.seen)


@pytest.mark.asyncio
async def test_abstained_tier_makes_the_case_abstain() -> None:
    # CA#5 (2026-11-12): both members give an empty answer, so the vote abstains no_votes; the
    # Case abstains with that reason and tier 2 never runs.
    gateway = Gateway(_replies((" ", " "), ("C", "C")))
    record = await run_gate(fixture("cascade_three.url4"), gateway)

    assert record["output"] == ""
    assert record.get("abstained") is True
    root = operations(record)["op_gate_1"]["decision"]
    assert root["result"] == {"status": "abstain", "reason": "no_votes"}
    assert all(request["model"] in _STAGE_ONE for request in gateway.seen)


@pytest.mark.asyncio
async def test_every_tier_escalates_and_the_case_abstains_gate_not_met() -> None:
    # CA#10 / CA-9 / CA-20 / BC#6a: the innermost word abstains; the root JOIN copies it.
    gateway = Gateway(_replies(("A", "B"), ("C", "D")))
    record = await run_gate(fixture("cascade_abstain.url4"), gateway)

    assert record["output"] == ""
    assert record.get("abstained") is True
    root = operations(record)["op_gate_1"]["decision"]
    assert root["result"] == {"status": "abstain", "reason": "gate_not_met"}
    assert len(gateway.seen) == 4  # every tier ran once


@pytest.mark.asyncio
async def test_every_tier_splits_and_sf_fail_fails_the_case() -> None:
    # CA#10 / CA-30: the last line holds, so the Case follows sf.fail().
    gateway = Gateway(_replies(("A", "B"), ("C", "D")))
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("cascade_fail_closed.url4"), gateway)
    assert caught.value.code == "fail_closed"
    assert len(gateway.seen) == 4


@pytest.mark.asyncio
async def test_every_tier_fails_and_the_first_failure_fails_the_case() -> None:
    # CA#11 / CA-19: the first tier's failure fails the Case; no later tier runs.
    gateway = Gateway(_replies((FAIL, FAIL), (FAIL, FAIL), large=FAIL))
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("cascade_three.url4"), gateway)
    assert caught.value.code == "aigateway_http_400"
    assert all(request["model"] in _STAGE_ONE for request in gateway.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "code"), [("cascade_abstain.url4", None), ("cascade_fail_closed.url4", "fail_closed")]
)
async def test_gated_last_tier_with_no_voters_follows_the_outcome(
    name: str, code: str | None
) -> None:
    # CA#11a / CA-30: tier 1 splits; tier 2 abstains (no voters). A Gate whose otherwise is an
    # outcome keeps the E4b rule: the Case abstains no_votes, or sf.fail() fails it.
    gateway = Gateway(_replies(("A", "B"), (" ", " ")))
    if code is None:
        record = await run_gate(fixture(name), gateway)
        assert record.get("abstained") is True
        root = operations(record)["op_gate_1"]["decision"]
        assert root["result"] == {"status": "abstain", "reason": "no_votes"}
    else:
        with pytest.raises(ResolutionError) as caught:
            await run_gate(fixture(name), gateway)
        assert caught.value.code == code
    assert "prov/large" not in {request["model"] for request in gateway.seen}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["cascade_abstain.url4", "cascade_fail_closed.url4"])
async def test_failed_last_tier_fails_the_case(name: str) -> None:
    # 2026-11-12: tier 2 keeps the author's quorum, so its failure fails the Case.
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture(name), Gateway(_replies(("A", "B"), (FAIL, FAIL))))
    assert caught.value.code == "aigateway_http_400"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "calls"),
    [("A\nConfidence: 90", 2), ("A\nConfidence: 40", 3)],
    ids=["kept", "escalated"],
)
async def test_signal_line_escalates_on_the_chosen_members_number(reply: str, calls: int) -> None:
    # 2026-11-12: sf.escalate_if(sf.signal("conf").chosen() < 70) reads the chosen member's value.
    gateway = Gateway({"prov/a": reply, "prov/b": reply, "prov/large": "L"})
    record = await run_gate(fixture("cascade_signal.url4"), gateway)

    assert len(gateway.seen) == calls
    assert (record["output"] == "L") is (calls == 3)


@pytest.mark.asyncio
async def test_missing_signal_fails_the_case_with_signal_missing() -> None:
    # 2026-11-12: no member wrote a confidence, so the line can neither keep nor escalate.
    gateway = Gateway({"prov/a": "A", "prov/b": "A", "prov/large": "L"})
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("cascade_signal.url4"), gateway)

    assert caught.value.code == "signal_missing"
    assert caught.value.permanent is True
    assert all(request["model"] != "prov/large" for request in gateway.seen)


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


@pytest.mark.asyncio
async def test_missing_signal_with_an_outcome_otherwise_keeps_the_e4b_rule() -> None:
    # 2026-11-12 boundary (rule scope: recipe otherwise only): a Gate whose otherwise is sf.fail()
    # follows it on a missing number, as in E4b; it does not raise signal_missing.
    gateway = Gateway({"prov/a": "A", "prov/b": "A"})
    with pytest.raises(ResolutionError) as caught:
        await run_gate(fixture("signal_fail.url4"), gateway)
    assert caught.value.code == "fail_closed"
