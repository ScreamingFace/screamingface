"""A combine call reads a Fusion quorum panel (OME-1289 E4a x OME-1557).

FEATURE: a reducer Fusion with ``quorum`` or optional members hands the combine call a ``panel``:
url4's broadcast rows, one per member that answered. A member with no row failed upstream and was
optional; it becomes a ``fail`` Answer with the reason ``missing`` and never votes.
STORY: as a researcher, a vote over five samples with ``quorum=3`` still answers when two optional
samples fail, and the evidence names the two members that did not answer.
INVARIANT defended: url4 checks the quorum and the required members before the combine call
runs; the combine call reads exactly the rows url4 wrote and refuses any other shape.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_support import run, spec_text, vote_spec

from screamingface_engine.combine.ports import CombineError


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


def _code(intent: str, context: str) -> str:
    with pytest.raises(CombineError) as caught:
        run(intent, context)
    return caught.value.code


# --- QR-5: the panel shape --------------------------------------------------------------------


def test_a_panel_with_every_member_reads_like_outputs() -> None:
    texts = {1: "same x", 2: "other y", 3: "third x"}
    from_panel = run(spec_text(vote_spec(3)), _panel_context(texts))
    from_outputs = run(
        spec_text(vote_spec(3)),
        json.dumps({"input": "q", "outputs": {f"member_{i}": t for i, t in texts.items()}}),
    )

    assert from_panel.output == from_outputs.output == texts[1]
    assert from_panel.evidence == from_outputs.evidence


@pytest.mark.parametrize(
    "panel",
    [
        json.dumps({"source_position": 1, "source_name": "member_1", "result": "x"}),
        json.dumps([{"source_position": 1, "source_name": "member_1"}]),
        json.dumps([{"source_position": 1, "source_name": "member_1", "result": "x", "extra": 1}]),
        _rows({1: "x"}).replace("member_1", "member_9"),
        _rows({1: "x"}).replace('"source_position": 1', '"source_position": 2'),
        _rows({1: "x"}).replace('"source_position": 1', '"source_position": true'),
        _rows({1: "x"}).replace('"result": "x"', '"result": null'),
        json.dumps(json.loads(_rows({1: "x"})) * 2),
        "not json",
    ],
    ids=[
        "not-a-list",
        "missing-key",
        "extra-key",
        "unknown-member",
        "wrong-position",
        "bool-position",
        "null-result",
        "duplicate-member",
        "not-json",
    ],
)
def test_a_panel_of_any_other_shape_is_spec_invalid(panel: str) -> None:
    context = json.dumps({"input": "q", "panel": panel})

    assert _code(spec_text(vote_spec(3)), context) == "combine_spec_invalid"


def test_a_panel_must_be_text_and_never_sits_beside_outputs() -> None:
    as_list = json.dumps({"input": "q", "panel": json.loads(_rows({1: "x"}))})
    both = json.dumps({"input": "q", "panel": _rows({1: "x"}), "outputs": {"member_1": "x"}})
    neither = json.dumps({"input": "q"})

    for context in (as_list, both, neither):
        assert _code(spec_text(vote_spec(3)), context) == "combine_spec_invalid"


# --- QR-6: a missing member fails and never votes ---------------------------------------------


def test_a_member_left_out_of_the_panel_is_a_missing_failure_that_does_not_vote() -> None:
    outcome = run(spec_text(vote_spec(3)), _panel_context({1: "one y", 3: "three x"}))

    members = {record.member_id: record for record in outcome.evidence.members}
    assert list(members) == ["member_1", "member_2", "member_3"]
    assert (members["member_2"].status, members["member_2"].reason) == ("fail", "missing")
    assert members["member_2"].raw is None and members["member_2"].value is None
    assert outcome.evidence.dropped == 1
    assert outcome.output == "one y"


def test_an_empty_panel_abstains_with_no_votes() -> None:
    outcome = run(spec_text(vote_spec(3)), _panel_context({}))

    assert outcome.output == ""
    assert outcome.evidence.result.status == "abstain"
    assert outcome.evidence.result.reason == "no_votes"
    assert outcome.evidence.dropped == 3
    assert {record.reason for record in outcome.evidence.members} == {"missing"}
