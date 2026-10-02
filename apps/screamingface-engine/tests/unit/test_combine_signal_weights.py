"""A signal-weighted vote through the built-in operators (OME-1289, E4a gap-closure, unit 2).

FEATURE: a vote weighted by a number each reply carries (``field:confidence``); a member with no
usable weight does not vote, and a vote nobody can cast abstains.
STORY: as an author of a confidence-weighted Candidate, a reply without a usable confidence is
left out of the count instead of failing the whole combine. SR#1 to SR#4 (SR-D1, SR-D6).
"""

from __future__ import annotations

import json
from typing import Any

from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_FIELD_CONFIDENCE = {"signal": "field:confidence"}


def _step(op_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"op": op_id, "args": {} if args is None else args}


def _signal_vote(count: int) -> dict[str, Any]:
    """A vote on ``answer`` weighted by ``field:confidence`` (built-in operators only)."""
    return vote_spec(
        count,
        extract=_step("json_field@1", {"path": "answer"}),
        normalize=_step("text@1"),
        reduce=_step("weighted_mode@1"),
        select=_step("max_weight_holder@1"),
        weights=_FIELD_CONFIDENCE,
    )


def _reply(answer: str, confidence: str) -> str:
    """A JSON reply whose confidence is given as raw JSON text (so 1e999 stays 1e999)."""
    return f'{{"answer": {json.dumps(answer)}, "confidence": {confidence}}}'


def test_fixed_weights_vote_is_unchanged() -> None:
    spec = vote_spec(
        3,
        extract=_step("last_number@1"),
        normalize=_step("numeric@1"),
        reduce=_step("weighted_mode@1"),
        select=_step("max_weight_holder@1"),
        weights={"member_1": 3.0, "member_2": 1.0, "member_3": 1.0},
    )
    outcome = run(spec_text(spec), context_text(["9", "12", "12"]), registry=BUILTIN_OPERATORS)
    evidence = outcome.evidence
    assert outcome.output == "9"
    assert [(row.value, row.score) for row in evidence.tally or []] == [("9", 3.0), ("12", 2.0)]
    assert evidence.signal is None
    assert [row.signals for row in evidence.members] == [{}, {}, {}]


def test_voter_with_missing_or_invalid_weight_signal_does_not_vote() -> None:
    confidences = ["0.9", "null", "0", "-1", '"0.8"', "1e999", "1e307"]
    replies = [
        _reply("A", confidence) if index < 2 else _reply("B", confidence)
        for index, confidence in enumerate(confidences)
    ]
    replies.append('{"answer": "B"}')
    assert len(replies) == 8
    outcome = run(spec_text(_signal_vote(8)), context_text(replies), registry=BUILTIN_OPERATORS)
    evidence = outcome.evidence
    assert outcome.output == replies[0]
    assert [row.model_dump() for row in evidence.tally or []] == [
        {"value": "a", "score": 0.9, "holders": ["member_1"]}
    ]
    assert all(row.weight is None and row.status == "answered" for row in evidence.members[1:])
    assert [row.signals["field:confidence"] for row in evidence.members] == [
        0.9,
        None,
        0.0,
        -1.0,
        None,
        None,
        1e307,
        None,
    ]


def test_all_weights_missing_abstains() -> None:
    replies = [_reply("A", "null"), _reply("B", "null"), '{"answer": "B"}']
    outcome = run(spec_text(_signal_vote(3)), context_text(replies), registry=BUILTIN_OPERATORS)
    evidence = outcome.evidence
    assert outcome.output == ""
    result = evidence.result
    assert (result.member_id, result.value, result.status, result.reason) == (
        None,
        None,
        "abstain",
        "no_votes",
    )
    assert evidence.tally is None
    assert evidence.dropped == 0


def test_vote_weighted_by_field_signal_picks_heaviest_answer() -> None:
    replies = [
        '{"answer":"A","confidence":0.9}',
        '{"answer":"B","confidence":0.3}',
        '{"answer":"B","confidence":0.4}',
    ]
    outcome = run(spec_text(_signal_vote(3)), context_text(replies), registry=BUILTIN_OPERATORS)
    evidence = outcome.evidence
    assert [(row.value, row.score, row.holders) for row in evidence.tally or []] == [
        ("a", 0.9, ["member_1"]),
        ("b", 0.7, ["member_2", "member_3"]),
    ]
    assert outcome.output == replies[0]
    result = evidence.result
    assert (result.member_id, result.value, result.status, result.reason) == (
        "member_1",
        "a",
        "answered",
        None,
    )
    assert evidence.signal is not None
    assert (evidence.signal.key, evidence.signal.order) == ("field:confidence", None)
    assert [row.weight for row in evidence.members] == [0.9, 0.3, 0.4]
