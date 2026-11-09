"""A declared signal works with the part 2 exclusion, rank and cut (E4b part 2 and part 3 restack).

FEATURE: E4b part 2 (member exclusion, rank and cut) on top of E4b part 3 (declared signals).
STORY: as a researcher, a rule that reads a declared name (``sf.Verbalized``, ``sf.Logprob``)
leaves out a member with no value for it, and a Rank by a declared name records the rank and the
cut, the same as for an E4a key.
INVARIANT defended: a member with no usable declared value is "excluded" with ``no_weight`` (the
weights read it) or ``no_signal`` (the reduce args read it); a declared name that no rule reads
never excludes a member; ``cut`` comes after ``signal`` and ``declared`` comes after ``cut`` in
the wire order.
"""

from __future__ import annotations

import json
from typing import Any

from combine_signal_support import argmax_spec, filter_spec, rank_signal_spec, sources
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import (
    REPLY_LOGPROB_SUM,
    REPLY_TOKENS,
    AccountingReader,
    MemberSources,
)

CONF = {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}
# member_3 states no confidence, so it has no value for "conf".
TEXTS = ["A\nConfidence: 90", "A\nConfidence: 40", "B\nno number"]


def _evidence(
    spec: dict[str, Any], context: str, accounting: AccountingReader | None = None
) -> dict[str, Any]:
    outcome = run(spec_text(spec), context, registry=BUILTIN_OPERATORS, accounting=accounting)
    return json.loads(outcome.evidence.model_dump_json(by_alias=True))


def _statuses(evidence: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(row["status"], row["reason"]) for row in evidence["members"]]


def test_a_weight_from_a_declared_name_excludes_a_member_with_no_value() -> None:
    spec = vote_spec(
        3,
        extract={"op": "last_line@1", "args": {}},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": "conf"},
        signals={"conf": CONF},
    )
    evidence = _evidence(spec, context_text(TEXTS))
    assert _statuses(evidence) == [
        ("answered", None),
        ("answered", None),
        ("excluded", "no_weight"),
    ]
    assert evidence["members"][2]["signals"] == {"conf": None}
    assert "member_3" not in evidence["chosen"]


def test_a_pick_and_a_filter_by_a_declared_name_exclude_a_member_with_no_value() -> None:
    pick = {**argmax_spec(3, "conf", "max"), "signals": {"conf": CONF}}
    kept = {**filter_spec(3, {"key": "conf", "cmp": "ge", "value": 50}), "signals": {"conf": CONF}}
    for spec in (pick, kept):
        evidence = _evidence(spec, context_text(TEXTS))
        assert _statuses(evidence)[2] == ("excluded", "no_signal")
        assert evidence["chosen"] == ["member_1"]


def test_a_declared_name_that_no_rule_reads_never_excludes_a_member() -> None:
    other = {"source": "verbalized", "pattern": "Other: ([0-9]+)"}  # no member states it
    spec = {**argmax_spec(3, "conf", "max"), "signals": {"conf": CONF, "other": other}}
    evidence = _evidence(spec, context_text(TEXTS))
    assert _statuses(evidence)[:2] == [("answered", None), ("answered", None)]
    assert [row["signals"]["other"] for row in evidence["members"]] == [None, None, None]


def test_a_rank_by_a_declared_name_records_the_rank_and_the_cut() -> None:
    spec = {**rank_signal_spec(3, 2, "conf", "max"), "signals": {"conf": CONF}}
    evidence = _evidence(spec, context_text(TEXTS))
    assert evidence["cut"] == {"k": 2, "order": "max"}
    assert [row.get("rank") for row in evidence["members"]] == [1, 2, None]
    assert _statuses(evidence)[2] == ("excluded", "no_signal")
    keys = list(evidence)
    assert keys.index("signal") + 1 == keys.index("cut")
    assert keys.index("cut") + 1 == keys.index("declared")


def test_a_rank_by_a_reply_logprob_excludes_a_member_with_no_reply_numbers() -> None:
    def reader(known: MemberSources, /) -> dict[str, dict[str, float | None]]:
        return {
            "member_1": {REPLY_TOKENS: 2.0, REPLY_LOGPROB_SUM: -1.0},
            "member_2": {REPLY_TOKENS: 2.0, REPLY_LOGPROB_SUM: -0.2},
            "member_3": {REPLY_TOKENS: None, REPLY_LOGPROB_SUM: None},
        }

    spec = {
        **rank_signal_spec(3, 1, "lp", "max"),
        "signals": {"lp": {"source": "logprob", "form": "mean"}},
    }
    context = {**json.loads(context_text(["A", "B", "C"])), "sources": sources(3)}
    evidence = _evidence(spec, json.dumps(context), reader)
    assert _statuses(evidence)[2] == ("excluded", "no_signal")
    assert [row.get("rank") for row in evidence["members"]] == [2, 1, None]
    assert evidence["chosen"] == ["member_2"]
