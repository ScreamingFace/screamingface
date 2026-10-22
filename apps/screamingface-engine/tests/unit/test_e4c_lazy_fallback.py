"""The E4b gate fallback is lazy: the judge or writer call runs only when the gate takes it.

FEATURE: E4c (OME-1291) lazy-fallback rows LF#4, #5, #6, #7, #8, #10, #11, #12, #13, #14, #15,
#16, #20; branch-core BC#11 (an E4b abstain still marks the Case).
STORY: as a researcher with a gated majority vote, the judge costs money only on the Cases where
the agreement fails; the evidence I read is what E4b writes, from call #2 on those Cases.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _gate_world import FAIL, Gateway, fixture, operations, run_gate
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import PendingCombine, run_combine_call
from screamingface_engine.combine.ports import SpecInvalid
from url4.core.errors import ResolutionError

_AGREE = {"prov/alpha": "A", "prov/beta": "A", "prov/gamma": "A"}
_SPLIT = {"prov/alpha": "A", "prov/beta": "A", "prov/gamma": "B"}


def _gated_vote() -> dict[str, Any]:
    spec = vote_spec(
        3,
        extract={"op": "last_line@1", "args": {}},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )
    return {
        **spec,
        "gate": {"cmp": ">=", "observe": "agreement", "otherwise": "judge", "threshold": 0.7},
    }


# --- the combine call (LF#4, #5, #14, #15) ------------------------------------------------------


def test_decision_call_fallback_branch_returns_the_pending_outcome() -> None:
    outcome = run_combine_call(
        BUILTIN_OPERATORS,
        {"binding": "synthesis_1", "phase": "decide"},
        context_text(["A", "A", "B"]),
        spec_text(_gated_vote()),
    )
    assert isinstance(outcome, PendingCombine)
    assert (outcome.record.branch, outcome.record.otherwise) == ("fallback", "judge")
    assert outcome.kept == "A"  # BU-18: the majority answer, for a budget-refused fallback


def test_run_combine_refuses_a_pending_decision_call() -> None:
    with pytest.raises(RuntimeError, match="runs through run_combine_call"):
        run(
            spec_text(_gated_vote()),
            context_text(["A", "A", "B"]),
            registry=BUILTIN_OPERATORS,
            params={"binding": "synthesis_1", "phase": "decide"},
        )


def test_decision_call_majority_evidence_equals_todays_bytes() -> None:
    # LF#5 / LF-4: on the majority branch the decision call writes E4b's evidence, byte for byte.
    texts = ["A", "A", "A"]
    today = run(spec_text(_gated_vote()), context_text(texts), registry=BUILTIN_OPERATORS)
    decision = run(
        spec_text(_gated_vote()),
        context_text(texts),
        registry=BUILTIN_OPERATORS,
        params={"binding": "synthesis_1", "phase": "decide"},
    )
    assert decision.output == today.output
    assert decision.evidence.model_dump_json(by_alias=True) == today.evidence.model_dump_json(
        by_alias=True
    )


def test_decision_call_with_a_fallback_key_is_spec_invalid() -> None:
    with pytest.raises(SpecInvalid, match="a decision call reads no fallback signal"):
        run(
            spec_text(_gated_vote()),
            context_text(["A", "A", "B"], {"fallback_judge": "member_3"}),
            registry=BUILTIN_OPERATORS,
            params={"binding": "synthesis_1", "phase": "decide"},
        )


@pytest.mark.parametrize(
    "params",
    [{"binding": "synthesis_1", "phase": "final"}, {"binding": "synthesis_1", "other": "x"}],
)
def test_combine_call_refuses_an_unknown_phase_or_param(params: dict[str, str]) -> None:
    with pytest.raises(SpecInvalid) as caught:
        run(
            spec_text(_gated_vote()),
            context_text(["A"] * 3),
            registry=BUILTIN_OPERATORS,
            params=params,
        )
    assert (
        str(caught.value) == "a combine call takes binding=synthesis_N and optionally phase=decide"
    )


# --- Engine world runs (LF#6 - #8, #10 - #13, #16, #20) ----------------------------------------


@pytest.mark.asyncio
async def test_judge_fallback_sends_no_judge_call_when_the_gate_passes() -> None:
    gateway = Gateway({**_AGREE, "prov/judge": "member_3"})
    record = await run_gate(fixture("lazy_judge.url4"), gateway)

    assert record["output"] == "A"
    assert gateway.calls("prov/judge") == 0
    decision = operations(record)["op_gate_1"]["decision"]
    assert decision["not_run"] == [
        {"branch": "otherwise", "reason": "not_selected", "model_calls": {"min": 1, "max": 1}}
    ]
    assert decision["result"] == {"status": "answered", "reason": None}
    assert operations(record)["op_synthesis_1"]["combine"]["gate"]["branch"] == "majority"


@pytest.mark.asyncio
async def test_judge_fallback_sends_one_judge_call_when_the_gate_fails() -> None:
    gateway = Gateway({**_SPLIT, "prov/judge": "member_3"})
    record = await run_gate(fixture("lazy_judge.url4"), gateway)

    assert record["output"] == "B"
    assert gateway.calls("prov/judge") == 1
    ops = operations(record)
    # LF-13: the pending call #1 is never the answer and carries no evidence.
    assert ops["op_synthesis_1"]["output"] == ""
    assert "combine" not in ops["op_synthesis_1"]
    assert ops["op_synthesis_2"]["combine"]["judge"]["parsed"] == "member_3"
    assert ops["op_gate_1"]["decision"]["branch"] == "otherwise"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("confidences", "writer_calls", "output", "abstained"),
    [
        ((90, 90, 90), 0, "A", False),  # the gate passes: no writer call
        ((10, 10, 10), 1, "W", False),  # the gate fails: the writer answers
        ((50, 50, 50), 0, "", True),  # inside the band: abstain in_band, no writer call (LF-5)
    ],
)
async def test_writer_fallback_runs_only_on_the_fallback_branch(
    confidences, writer_calls, output, abstained
) -> None:
    replies = {
        model: f"Confidence: {value}\nA"
        for model, value in zip(("prov/alpha", "prov/beta", "prov/gamma"), confidences, strict=True)
    }
    gateway = Gateway({**replies, "prov/writer": "W"})
    record = await run_gate(fixture("lazy_writer.url4"), gateway)

    assert gateway.calls("prov/writer") == writer_calls
    assert record["output"] == (replies["prov/alpha"] if output == "A" else output)
    assert record.get("abstained", False) is abstained


@pytest.mark.asyncio
async def test_no_voter_sends_no_fallback_call_and_abstains_no_votes() -> None:
    # LF-6 / LF#11 / BC#11: every member gives an empty answer, so the vote has no voter.
    gateway = Gateway({"prov/alpha": " ", "prov/beta": " ", "prov/gamma": " ", "prov/judge": "x"})
    record = await run_gate(fixture("lazy_judge.url4"), gateway)

    assert gateway.calls("prov/judge") == 0
    assert record.get("abstained") is True
    decision = operations(record)["op_gate_1"]["decision"]
    assert (decision["wanted"], decision["branch"]) == (None, None)
    assert decision["result"] == {"status": "abstain", "reason": "no_votes"}


@pytest.mark.asyncio
async def test_fallback_failure_fails_the_case_only_on_the_fallback_branch() -> None:
    # LF-7, LF-8: a judge that would fail never fails a Case whose gate passes.
    passed = await run_gate(fixture("lazy_judge.url4"), Gateway({**_AGREE, "prov/judge": FAIL}))
    assert passed["output"] == "A"
    with pytest.raises(ResolutionError):
        await run_gate(fixture("lazy_judge.url4"), Gateway({**_SPLIT, "prov/judge": FAIL}))


@pytest.mark.asyncio
async def test_replay_sends_the_fallback_on_the_same_cases() -> None:
    # LF#13 / LF-12: the same inputs take the same branch on a second run.
    for replies, judge_calls in ((_AGREE, 0), (_SPLIT, 1)):
        runs = []
        for _ in range(2):
            gateway = Gateway({**replies, "prov/judge": "member_3"})
            record = await run_gate(fixture("lazy_judge.url4"), gateway)
            runs.append((gateway.calls("prov/judge"), operations(record)["op_gate_1"]["decision"]))
        assert runs[0] == runs[1]
        assert runs[0][0] == judge_calls


@pytest.mark.asyncio
async def test_run_accounting_counts_only_the_fallback_calls_that_ran() -> None:
    # LF#16 / LF-15: of three Cases one fails the gate, so one judge operation has accounting.
    judge_rows = 0
    for replies in (_AGREE, _AGREE, _SPLIT):
        record = await run_gate(
            fixture("lazy_judge.url4"), Gateway({**replies, "prov/judge": "member_3"})
        )
        judge = operations(record).get("op_judge_1")
        judge_rows += judge is not None and judge["accounting"] is not None
    assert judge_rows == 1


@pytest.mark.asyncio
async def test_e4b_one_call_url4_still_runs_on_the_engine() -> None:
    # LF#20: an E4b-era url4 (no phase param, the judge in the combine deps) runs as before.
    gateway = Gateway({**_AGREE, "prov/judge": "member_3"})
    record = await run_gate(fixture("e4b_one_call_judge.url4"), gateway)
    assert record["output"] == "A"
    assert gateway.calls("prov/judge") == 1  # E4b: the fallback runs on every Case
    combine = operations(record)["op_synthesis_1"]["combine"]
    assert json.dumps(combine["gate"]["branch"]) == '"majority"'
