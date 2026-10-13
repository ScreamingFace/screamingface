"""A judge reads a Fusion quorum panel (OME-1289 E4a x OME-1557).

FEATURE: over a quorum panel the judge sees only the members that answered, so its label must name
one of them and its scores must cover exactly them; a member the panel left out gets no judge
weight. An empty panel abstains before the judge reply is read.
STORY: as a researcher, a judge Fusion with an optional member that failed still picks among the
members that answered, and never fails the Case for the member it could not see.
INVARIANT defended: the judge reply is still read strictly, against the members that answered.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_flow_support import judge_spec
from combine_support import run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import JudgeReplyInvalid
from screamingface_engine.combine.registry import OperatorRegistry

_BUILTINS = OperatorRegistry(BUILTIN_OPERATORS)


def _rows(texts: dict[int, str]) -> str:
    """The broadcast rows url4 writes for the members that answered (1-based positions)."""
    return json.dumps(
        [
            {"source_position": index, "source_name": f"member_{index}", "result": answer}
            for index, answer in texts.items()
        ]
    )


def _panel_context(texts: dict[int, str], **extra: Any) -> str:
    return json.dumps({"input": "q", "panel": _rows(texts), **extra})


# --- QR-7: a judge reads the members that answered --------------------------------------------


def test_a_judge_label_may_name_only_a_member_that_answered() -> None:
    spec = spec_text(judge_spec(3, "label"))
    texts = {1: "alpha", 3: "gamma"}

    chosen = run(spec, _panel_context(texts, signals={"judge": "member_3"}), registry=_BUILTINS)

    assert chosen.output == "gamma"
    with pytest.raises(JudgeReplyInvalid):
        run(spec, _panel_context(texts, signals={"judge": "member_2"}), registry=_BUILTINS)


def test_judge_scores_cover_exactly_the_members_that_answered() -> None:
    spec = spec_text(judge_spec(3, "scores"))
    texts = {1: "alpha", 3: "gamma"}
    present = json.dumps({"member_1": 0.2, "member_3": 0.9})
    every = json.dumps({"member_1": 0.2, "member_2": 0.5, "member_3": 0.9})

    chosen = run(spec, _panel_context(texts, signals={"judge": present}), registry=_BUILTINS)

    assert chosen.output == "gamma"
    with pytest.raises(JudgeReplyInvalid):
        run(spec, _panel_context(texts, signals={"judge": every}), registry=_BUILTINS)


def test_a_judge_weighted_vote_gives_a_missing_member_no_weight() -> None:
    spec = vote_spec(
        3,
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
        weights={"signal": "score:judge"},
    )
    context = _panel_context(
        {1: "so 7", 3: "so 12"}, signals={"judge": '{"member_1":1,"member_3":3}'}
    )

    outcome = run(spec_text(spec), context, registry=_BUILTINS)

    assert outcome.output == "so 12"
    weights = {record.member_id: record.weight for record in outcome.evidence.members}
    assert weights["member_2"] is None


def test_an_empty_panel_abstains_before_the_judge_reply_is_read() -> None:
    spec = vote_spec(
        3,
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
        weights={"signal": "score:judge"},
    )
    context = _panel_context({}, signals={"judge": "I cannot score an empty panel."})

    outcome = run(json.dumps(spec), context, registry=_BUILTINS)

    assert (outcome.evidence.result.status, outcome.evidence.result.reason) == (
        "abstain",
        "no_votes",
    )
    assert {m.reason for m in outcome.evidence.members} == {"missing"}
