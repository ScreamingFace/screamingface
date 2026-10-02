"""One judge reply parser in the core, and ``score:judge`` as a signal (OME-1289 E4a, unit 8E).

FEATURE: the core reads each member's ``score:judge`` from the strict judge reply, so a vote can be
weighted by a judge and a reducer can rank by it. SG#13 and SR#11 (engine part).
INVARIANT defended: the judge reply is never read loosely. A missing judge signal is a spec error,
and a malformed or oversize reply is ``judge_reply_invalid``; a message never repeats the reply.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_support import FAKE_REGISTRY, context_text, request, run, spec_text, vote_spec

from screamingface_engine.combine import ports
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import ResultRecord, SignalRecord
from screamingface_engine.combine.operators import judge
from screamingface_engine.combine.ports import (
    JUDGE_SIGNAL,
    CombineError,
    JudgeReplyInvalid,
    SpecInvalid,
    is_signal_key,
)
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.combine import CombineRoute
from url4.core.errors import ResolutionError

# --- SG#13 part 1: the parser and the cap live in ports ---------------------------------------


def test_parse_scores_and_the_reply_cap_live_in_ports() -> None:
    assert getattr(ports, "parse_scores", None) is judge.parse_scores
    assert getattr(ports, "MAX_JUDGE_REPLY_BYTES", None) == judge.MAX_JUDGE_REPLY_BYTES == 65536
    assert not hasattr(judge, "_unfenced")
    assert not hasattr(judge, "_score")


def test_judge_reply_names_the_owner_and_caps_at_64_kib() -> None:
    judge_reply: Any = getattr(ports, "judge_reply", None)
    assert callable(judge_reply)
    with pytest.raises(SpecInvalid, match="x@1 needs the judge signal"):
        judge_reply({}, "x@1")
    at_cap = "a" * 65536
    assert judge_reply({"judge": at_cap}, "x@1") == at_cap
    with pytest.raises(JudgeReplyInvalid):
        judge_reply({"judge": "a" * 65537}, "x@1")
    two_byte = "é" * 16385  # 32770 bytes: the cap counts bytes, not characters
    assert judge_reply({"judge": two_byte}, "x@1") == two_byte


# --- SG#13: score:judge is a signal key --------------------------------------------------------


def test_score_judge_is_a_signal_key() -> None:
    assert is_signal_key("score:judge")
    assert JUDGE_SIGNAL == "score:judge"
    for key in ("score:Judge", "score:", "score:judge2", "judge"):
        assert not is_signal_key(key)


_REPLY = '```json\n{"member_3": 0.5, "member_1": 0.2, "member_2": 0.9}\n```'


def _argmax_spec(**overrides: Any) -> dict[str, Any]:
    return vote_spec(
        3,
        reduce={"op": "fake_signal_score@1", "args": {"key": "score:judge", "order": "max"}},
        select={"op": "fake_best@1", "args": {}},
        **overrides,
    )


def test_judge_score_signal_per_member() -> None:
    outcome = run(
        spec_text(_argmax_spec()),
        context_text(["a x", "b y", "c z"], {"judge": _REPLY}),
        registry=FAKE_REGISTRY,
    )
    evidence = outcome.evidence
    assert [m.signals for m in evidence.members] == [
        {"score:judge": 0.2},
        {"score:judge": 0.9},
        {"score:judge": 0.5},
    ]
    assert [m.score for m in evidence.members] == [0.2, 0.9, 0.5]
    assert evidence.chosen == ["member_2"]
    assert evidence.signal == SignalRecord(key="score:judge", order="max")
    assert evidence.presentation_order == "author"
    assert evidence.judge is None


def test_judge_score_signal_as_the_vote_weight() -> None:
    spec = vote_spec(
        3, reduce={"op": "fake_weighted@1", "args": {}}, weights={"signal": JUDGE_SIGNAL}
    )
    outcome = run(
        spec_text(spec),
        context_text(["a x", "b y", "c z"], {"judge": _REPLY}),
        registry=FAKE_REGISTRY,
    )
    assert [m.weight for m in outcome.evidence.members] == [0.2, 0.9, 0.5]


def test_score_judge_without_a_judge_signal_is_spec_invalid() -> None:
    spec = _argmax_spec(extract={"op": "fake_bad_stage@1", "args": {}})
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a x", "b y", "c z"]), registry=FAKE_REGISTRY)
    assert caught.value.code == "combine_spec_invalid"
    assert "score:judge needs the judge signal" in str(caught.value)


_BAD_REPLIES = [
    ('{"member_1": 1}', ports._SCORES_INVALID),
    ("I like member 2", ports._SCORES_INVALID),
    ('{"member_1": NaN, "member_2": 1, "member_3": 1}', ports._SCORES_INVALID),
    ("member_1" + " " * 65536, ports._JUDGE_REPLY_TOO_LARGE),
]


@pytest.mark.parametrize(
    ("reply", "message"), _BAD_REPLIES, ids=["missing", "prose", "nan", "oversize"]
)
def test_a_malformed_or_oversized_judge_reply_fails_the_signal_read(
    reply: str, message: str
) -> None:
    spec = _argmax_spec(extract={"op": "fake_bad_stage@1", "args": {}})
    context = context_text(["a x", "b y", "c z"], {"judge": reply})
    # F11: the signal read runs before any extractor, so the bad extractor is never reached.
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context, registry=FAKE_REGISTRY)
    assert caught.value.code == "judge_reply_invalid"
    # The whole message is the fixed rule text, so it cannot hold any of the reply.
    assert str(caught.value) == message

    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as resolved:
            CombineRoute(FAKE_REGISTRY)(request(spec_text(spec), context))
    assert resolved.value.permanent is True
    assert list(calls) == []


# --- SR#11: a judge score as a vote weight ------------------------------------------------------


def _judge_weighted_spec() -> dict[str, Any]:
    return vote_spec(
        3,
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": JUDGE_SIGNAL},
    )


def _weighted(reply: str) -> Any:
    return run(
        spec_text(_judge_weighted_spec()),
        context_text(["A 7", "B 9", "C 9"], {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )


def _tally(outcome: Any) -> list[tuple[str, float, list[str]]]:
    return [(r.value, r.score, r.holders) for r in outcome.evidence.tally]


def test_judge_score_signal_weights_a_vote() -> None:
    outcome = _weighted('{"member_1": 0.9, "member_2": 0.3, "member_3": 0.4}')
    evidence = outcome.evidence
    assert outcome.output == "A 7"
    assert _tally(outcome) == [("7", 0.9, ["member_1"]), ("9", 0.7, ["member_2", "member_3"])]
    assert evidence.result == ResultRecord(
        member_id="member_1", value="7", status="answered", reason=None
    )
    assert [m.weight for m in evidence.members] == [0.9, 0.3, 0.4]
    assert evidence.signal == SignalRecord(key="score:judge", order=None)
    assert evidence.judge is None
    assert evidence.presentation_order == "author"


def test_a_judge_score_at_or_below_zero_does_not_vote() -> None:
    outcome = _weighted('{"member_1": 0, "member_2": -1, "member_3": 2}')
    evidence = outcome.evidence
    assert outcome.output == "C 9"
    assert _tally(outcome) == [("9", 2.0, ["member_3"])]
    assert [m.weight for m in evidence.members] == [None, None, 2.0]
    assert [m.signals["score:judge"] for m in evidence.members] == [0.0, -1.0, 2.0]
    assert [m.status for m in evidence.members] == ["answered"] * 3

    nobody = _weighted('{"member_1": 0, "member_2": 0, "member_3": -5}')
    assert nobody.output == ""
    assert nobody.evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert nobody.evidence.tally is None
    assert nobody.evidence.dropped == 0
