"""The stage after an empty Rank or Filter cut still gets the Case input (E4b fix, 2026-10-14).

FEATURE (ans:Q7 with ans:Q4): a Rank or Filter combine step that abstains (``cut_not_met`` or
``no_votes``) keeps the abstain in its evidence, and its output is the empty selection envelope
``{"input":"<the Fusion input>","selected":[]}``. So a later stage still sees the question.
STORY: as a benchmark author, when no member passes my Filter, the writer still sees the Case
question and can say that no draft was usable; it does not reply "there was no question".
INVARIANT defended: the abstain status and reason do not change; only a select operator that
declares ``envelope`` (``top_k@1``, ``kept@1``) hands on the envelope, and every other abstain
stays the empty text; an abstained last step still abstains the Case with the empty answer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate
from combine_selection_support import rank_spec
from combine_signal_support import filter_spec
from combine_support import context_text, fake_no_votes, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS, BUILTIN_REGISTRATIONS
from screamingface_engine.combine.evidence import ResultRecord
from screamingface_engine.combine.ports import (
    CombineError,
    OperatorDescriptor,
    canonical_json,
)

_QUESTION = "What is 6*7?"
_EMPTY = '{"input":"What is 6*7?","selected":[]}'
_FILTER_ARGS = {"cmp": "ge", "key": "field:confidence", "value": 0.6}
_LOW = ['{"confidence":0.1}', '{"confidence":0.5}', '{"confidence":0.2}']
# '{"input":"' (10 characters) + n + '","selected":[]}' (16 characters) = n + 26.
_EMPTY_OVERHEAD = 26
_CAP = 8 * 1024 * 1024  # MAX_RESULT_BYTES, written out: 8388608
_DATA = Path(__file__).parent / "data" / "combine_contract"
# The empty envelope around the Case input that run_candidate links ("what is 2 + 2?").
_CASE_EMPTY = '{"input":"what is 2 + 2?","selected":[]}'
_WRITER = "provider/writer"


def _context(question: str, outputs: Sequence[str]) -> str:
    """A combine context with this ``input`` (``context_text`` fixes it to "q")."""
    body = {
        "input": question,
        "outputs": {f"member_{index}": text for index, text in enumerate(outputs, start=1)},
    }
    return json.dumps(body)


def _filter(question: str, outputs: Sequence[str], extract: Mapping[str, Any] | None = None) -> Any:
    return run(
        spec_text(filter_spec(len(outputs), _FILTER_ARGS, extract)),
        _context(question, outputs),
        registry=BUILTIN_OPERATORS,
    )


def _recipe(name: str) -> str:
    return (_DATA / name).read_text(encoding="utf-8").removesuffix("\n")


def _last_stage(name: str) -> str:
    """The recipe without its writer: the selection Fusion is the last stage (hand-written url4).

    WHY hand-written: the SDK refuses a selection that ends a Candidate, so only a url4 author
    can make one. The engine must still abstain that Case with the empty answer.
    """
    head, found, _ = _recipe(name).partition(", model_4:0.0:")
    assert found, f"{name} has no model_4 writer stage"
    return head + ")!'$synthesis_1'"


def _models(replies: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    return {route: (reply, "0.001") for route, reply in replies.items()}


def _writer_messages(seen: list[dict[str, Any]]) -> list[str]:
    return [call["messages"][-1]["content"] for call in seen if call["model"] == _WRITER]


# --- ECE#1 filter with no pass ----------------------------------------------------------------


def test_filter_with_no_pass_hands_on_the_empty_envelope() -> None:
    outcome = _filter(_QUESTION, _LOW)

    assert outcome.output == _EMPTY
    assert outcome.evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert (outcome.evidence.chosen, outcome.evidence.built) == ([], False)
    assert [m.score for m in outcome.evidence.members] == [0.0, 0.0, 0.0]


# --- ECE#2 no member can be read ----------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        filter_spec(3, _FILTER_ARGS, {"op": "json_field@1", "args": {"path": "verdict"}}),
        rank_spec(3, 2, "field"),
    ],
    ids=["filter", "rank"],
)
def test_selection_with_no_voter_hands_on_the_empty_envelope(spec: dict[str, Any]) -> None:
    outcome = run(
        spec_text(spec),
        _context(_QUESTION, ["not json", "plain text", ""]),
        registry=BUILTIN_OPERATORS,
    )

    assert outcome.output == _EMPTY
    assert outcome.evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert [m.status for m in outcome.evidence.members] == ["fail", "fail", "fail"]


# --- ECE#3 (CHAR) other abstains keep the empty text --------------------------------------------


def test_an_abstain_of_another_select_step_keeps_the_empty_text() -> None:
    spec = vote_spec(2, select={"op": "fake_cut@1", "args": {}})

    outcome = run(spec_text(spec), context_text(["a x", "b y"]))

    assert outcome.output == ""
    assert outcome.evidence.result.reason == "cut_not_met"


# --- ECE#4 the input round-trips ----------------------------------------------------------------


def test_empty_envelope_round_trips_unicode_quotes_and_newlines() -> None:
    question = 'say "hi"\nthen café 中文 \\ end'

    outcome = _filter(question, _LOW)

    assert outcome.output == '{"input":"say \\"hi\\"\\nthen café 中文 \\\\ end","selected":[]}'
    assert outcome.output == canonical_json({"input": question, "selected": []})
    assert json.loads(outcome.output) == {"input": question, "selected": []}


# --- ECE#5 the 8 MiB result cap -----------------------------------------------------------------


def test_oversized_empty_envelope_fails_like_any_oversized_result() -> None:
    at_cap = "x" * (_CAP - _EMPTY_OVERHEAD)  # 8388582 characters: the envelope is 8388608 bytes
    fits = _filter(at_cap, _LOW[:2])
    assert len(fits.output.encode("utf-8")) == _CAP
    assert fits.evidence.result.status == "abstain"

    with pytest.raises(CombineError) as caught:
        _filter(at_cap + "x", _LOW[:2])

    assert caught.value.code == "combine_input_too_large"


# --- ECE#6 which operators hand on the envelope ---------------------------------------------------


def test_only_top_k_and_kept_hand_on_the_envelope() -> None:
    marked = sorted(d.id for d in BUILTIN_REGISTRATIONS if d.envelope)
    assert marked == ["kept@1", "top_k@1"]
    assert all("envelope" not in d.catalog_entry() for d in BUILTIN_REGISTRATIONS)


def test_only_a_select_operator_may_hand_on_the_envelope() -> None:
    with pytest.raises(ValueError, match="only a select operator may hand on the envelope"):
        OperatorDescriptor("mark", 1, "reduce", "A reduce step.", fake_no_votes, envelope=True)


# --- ECE#7 a Rank cut in a Pipeline (engine world) --------------------------------------------


@pytest.mark.asyncio
async def test_rank_cut_not_met_writer_gets_the_case_input() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _recipe("recipe_s7.url4"),
        _models(
            {
                "provider/alpha": '{"answer":"A","confidence":0.9}',
                "provider/beta": "plain text",
                "provider/gamma": '{"answer":"C"}',
                _WRITER: "final answer",
            }
        ),
        "miss",
        on_request=seen.append,
    )

    synthesis = operation(record, "op_synthesis_1")
    assert synthesis["output"] == _CASE_EMPTY
    assert synthesis["combine"]["result"]["status"] == "abstain"
    assert synthesis["combine"]["result"]["reason"] == "cut_not_met"
    assert synthesis["combine"]["chosen"] == []
    assert _writer_messages(seen) == [_CASE_EMPTY]
    assert not record.get("abstained", False)
    assert record["output"] == "final answer"


# --- ECE#8 a selection that is the last stage --------------------------------------------------


@pytest.mark.asyncio
async def test_an_abstained_last_selection_still_abstains_the_case() -> None:
    seen: list[dict[str, Any]] = []
    record = await run_candidate(
        _last_stage("recipe_s9.url4"),
        _models(
            {
                "provider/alpha": '{"answer":"A","confidence":0.7}',
                "provider/beta": '{"answer":"B","confidence":0.2}',
                "provider/gamma": '{"answer":"C","confidence":0.5}',
            }
        ),
        "miss",
        on_request=seen.append,
    )

    synthesis = operation(record, "op_synthesis_1")
    assert synthesis["output"] == _CASE_EMPTY
    assert synthesis["combine"]["result"]["reason"] == "no_votes"
    assert record["status"] == "completed"
    assert record["output"] == ""
    assert record["abstained"] is True
    assert len(seen) == 3
