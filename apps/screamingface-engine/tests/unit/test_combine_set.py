"""set@1 turns a list answer into one comparable value (OME-1289, E4a gap-closure, unit 2).

FEATURE: members that list the same items in a different order or shape vote together.
STORY: as an author of a Candidate that answers with a list ("which cities?"), ``["Paris",
"Rome"]`` and ``rome, paris`` count as one answer. RX#8 and RX#9 (RX-D3).
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_golden_support import stage
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import StageResult


def _set(raw: str) -> StageResult:
    return stage("set@1", raw)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ('["Paris","Rome"]', '["paris","rome"]'),
        ("rome, paris", '["paris","rome"]'),
        ("b, a, a", '["a","b"]'),
        ('["a","b"]', '["a","b"]'),
        ("new   york, Paris", '["new york","paris"]'),
        ("[1, 2.5, true]", '["1","2.5","true"]'),
    ],
)
def test_set_normalizes_json_list_and_comma_text_to_one_value(raw: str, value: str) -> None:
    assert _set(raw) == StageResult(value, "voted")


def _list_vote(count: int, extract: dict[str, Any]) -> dict[str, Any]:
    return vote_spec(
        count,
        extract=extract,
        normalize={"op": "set@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )


def test_set_votes_agree_across_json_fields_and_plain_text() -> None:
    spec = _list_vote(2, {"op": "json_field@1", "args": {"path": "cities"}})
    texts = ['{"cities":["Paris","Rome"]}', '{"cities":["rome","paris"]}']
    outcome = run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)
    assert [(row.value, row.holders) for row in outcome.evidence.tally or []] == [
        ('["paris","rome"]', ["member_1", "member_2"])
    ]
    plain = run(
        spec_text(_list_vote(2, {"op": "whole@1", "args": {}})),
        context_text(["rome, paris", "Paris,Rome"]),
        registry=BUILTIN_OPERATORS,
    )
    assert [row.value for row in plain.evidence.tally or []] == ['["paris","rome"]']


@pytest.mark.parametrize("raw", ['[["a"]]', "[null]", '[{"a":1}]', "[1e999]", "[oops"])
def test_set_rejects_nested_items_as_not_json(raw: str) -> None:
    assert _set(raw) == StageResult(None, "not_json")


def test_set_rejects_oversize_and_empty_lists() -> None:
    many = ",".join(f"item{index}" for index in range(257))
    assert _set(many) == StageResult(None, "too_large")
    assert _set(many.rsplit(",", 1)[0]).status == "voted"
    assert _set(",") == StageResult(None, "empty")
    assert _set("[]") == StageResult(None, "empty")
