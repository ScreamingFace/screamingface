"""The output of Rank and Filter carries the Case input (E4b unit 1, selection input).

FEATURE (ans:Q7, P4): ``top_k@1`` and ``kept@1`` put the combine context ``input`` into their
selection JSON, so the stage after a Rank or a Filter sees the question:
``{"input": "<input>", "selected": [{"id", "text"}]}``. ``join@1`` and ``all@1`` (Concat) do not
change (ans:Q13).
STORY: as a benchmark author, the writer after a Rank or a Filter can answer a different question
in each Case, and I do not have to put the question into the writer prompt.
INVARIANT defended: the input is copied verbatim (CI-I1, SI-D4); an envelope over the 8 MiB result
cap fails with the same code as any oversized output, and the input is never cut (SI-E2); a cut
that is not met abstains and hands on the empty envelope ``{"input":"...","selected":[]}`` (SI-E1,
E4b fix 2026-10-14).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest
from combine_selection_support import concat_spec, rank_spec
from combine_signal_support import filter_spec
from combine_support import run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS, BUILTIN_REGISTRATIONS
from screamingface_engine.combine.ports import (
    CombineError,
    CombineInput,
    OpArgs,
    Reduction,
    Selection,
    SelectOp,
    canonical_json,
)
from screamingface_engine.combine.registry import OperatorRegistry

_QUESTION = "What is 6*7?"
_FILTER_ARGS = {"cmp": "ge", "key": "field:confidence", "value": 0.6}
# The envelope around a question of n "x" characters and one kept member "B" (member_2):
# '{"input":"' (10) + n + '","selected":[{"id":"member_2","text":"B"}]}' (44) = n + 54.
_ONE_KEPT_OVERHEAD = 54
_CAP = 8 * 1024 * 1024  # MAX_RESULT_BYTES, written out: 8388608


def _context(
    question: str, outputs: Sequence[str], signals: Mapping[str, str] | None = None
) -> str:
    """A combine context with this ``input`` (``combine_support.context_text`` fixes it to "q")."""
    body: dict[str, Any] = {
        "input": question,
        "outputs": {f"member_{index}": text for index, text in enumerate(outputs, start=1)},
    }
    if signals is not None:
        body["signals"] = dict(signals)
    return json.dumps(body)


def _judge(*scores: float) -> dict[str, str]:
    return {"judge": canonical_json({f"member_{i}": s for i, s in enumerate(scores, start=1)})}


def _rank(question: str, texts: Sequence[str], scores: Sequence[float], k: int) -> Any:
    return run(
        spec_text(rank_spec(len(texts), k)),
        _context(question, texts, _judge(*scores)),
        registry=BUILTIN_OPERATORS,
    )


# --- SI#1 (CHAR) SI-3 ---------------------------------------------------------------------------


def test_concat_output_is_the_joined_text() -> None:
    outcome = run(
        spec_text(concat_spec(2)),
        _context(_QUESTION, ["A", "B"]),
        registry=BUILTIN_OPERATORS,
    )

    assert outcome.output == "[member_1]\nA\n\n---\n\n[member_2]\nB"


# --- SI#3 SI-1 ----------------------------------------------------------------------------------


def test_top_k_envelope_has_the_input_and_the_selected_members() -> None:
    outcome = _rank(_QUESTION, ["A", "B", "C"], [0.5, 0.9, 0.1], 2)

    assert outcome.output == (
        '{"input":"What is 6*7?","selected":'
        '[{"id":"member_2","text":"B"},{"id":"member_1","text":"A"}]}'
    )


# --- SI#4 SI-2 ----------------------------------------------------------------------------------


def test_kept_envelope_has_the_input_and_the_kept_members() -> None:
    texts = ['{"confidence":0.9}', '{"confidence":0.2}', '{"confidence":0.7}']

    outcome = run(
        spec_text(filter_spec(3, _FILTER_ARGS)),
        _context(_QUESTION, texts),
        registry=BUILTIN_OPERATORS,
    )

    assert outcome.output == (
        '{"input":"What is 6*7?","selected":'
        '[{"id":"member_1","text":"{\\"confidence\\":0.9}"},'
        '{"id":"member_3","text":"{\\"confidence\\":0.7}"}]}'
    )


# --- SI#5 CI-I1 ---------------------------------------------------------------------------------


def test_combine_input_carries_the_context_input_verbatim() -> None:
    seen: list[CombineInput] = []
    real = next(d for d in BUILTIN_REGISTRATIONS if d.id == "top_k@1")
    select_run = cast("SelectOp", real.run)

    def spy(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
        seen.append(combine_input)
        return select_run(reduction, combine_input, args)

    registry = OperatorRegistry(
        dataclasses.replace(d, run=spy) if d.id == "top_k@1" else d for d in BUILTIN_REGISTRATIONS
    )
    run(
        spec_text(rank_spec(2, 1)),
        _context(" two  spaces\tand a tab \n", ["A", "B"], _judge(0.1, 0.9)),
        registry=registry,
    )

    assert [combine_input.input for combine_input in seen] == [" two  spaces\tand a tab \n"]


# --- SI#6 SI-D4 ---------------------------------------------------------------------------------


def test_envelope_round_trips_unicode_quotes_and_newlines() -> None:
    question = 'say "hi"\nthen café 中文 \\ end'

    outcome = _rank(question, ["A", "B"], [0.1, 0.9], 1)

    assert outcome.output == (
        '{"input":"say \\"hi\\"\\nthen café 中文 \\\\ end",'
        '"selected":[{"id":"member_2","text":"B"}]}'
    )
    assert json.loads(outcome.output)["input"] == question


# --- SI#10 SI-D1 --------------------------------------------------------------------------------


def test_conversation_input_appears_as_json_text_in_the_envelope() -> None:
    conversation = (
        '{"messages":[{"content":"Hi","role":"user"},{"content":"Hello","role":"assistant"},'
        '{"content":"What is 6*7?","role":"user"}],"schema":"screamingface.candidate-input.v1"}'
    )

    outcome = _rank(conversation, ["A", "B"], [0.9, 0.1], 1)

    envelope = json.loads(outcome.output)
    assert envelope == {
        "input": conversation,
        "selected": [{"id": "member_1", "text": "A"}],
    }
    assert isinstance(envelope["input"], str)


# --- SI#11 SI-E2, SI-D3 -------------------------------------------------------------------------


def test_oversized_envelope_fails_like_any_oversized_result() -> None:
    at_cap = "x" * (_CAP - _ONE_KEPT_OVERHEAD)  # 8388554 characters: the envelope is 8388608
    fits = _rank(at_cap, ["A", "B"], [0.1, 0.9], 1)
    assert len(fits.output.encode("utf-8")) == _CAP
    assert json.loads(fits.output)["input"] == at_cap

    with pytest.raises(CombineError) as caught:
        _rank(at_cap + "x", ["A", "B"], [0.1, 0.9], 1)

    assert caught.value.code == "combine_input_too_large"


# --- SI#13 SI-E1 --------------------------------------------------------------------------------


def test_rank_cut_not_met_abstains_with_the_empty_envelope() -> None:
    # member_2 has no "score" field, so only two members are ranked and k=3 is not met
    outcome = run(
        spec_text(rank_spec(3, 3, "field")),
        _context(_QUESTION, ['{"score":5}', "no score", '{"score":7}']),
        registry=BUILTIN_OPERATORS,
    )

    # E4b fix (2026-10-14): the abstain hands on the empty envelope, with the input
    assert outcome.output == '{"input":"What is 6*7?","selected":[]}'
    assert (outcome.evidence.result.status, outcome.evidence.result.reason) == (
        "abstain",
        "cut_not_met",
    )
    assert (outcome.evidence.chosen, outcome.evidence.built) == ([], False)
    assert [m.score for m in outcome.evidence.members] == [5.0, None, 7.0]
