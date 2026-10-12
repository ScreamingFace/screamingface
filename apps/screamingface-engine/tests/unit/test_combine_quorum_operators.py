"""Every built-in combine shape over a quorum panel with a missing member (OME-1289 unit 13).

FEATURE: the specs below are the SDK's own compiled specs (README goldens and the filter contract
fixture). Over a panel, each reducer reads only the members that answered: concat joins them, rank
cuts among them, filter marks them, and argmax by cost picks among them.
INVARIANT defended: a missing member never takes a slot, a rank place, a pass mark or a cost.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from combine_support import run
from test_combine_signals import _sources

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import MemberSources
from screamingface_engine.combine.registry import OperatorRegistry

_BUILTINS = OperatorRegistry(BUILTIN_OPERATORS)
_SEPARATOR = "\n\n---\n\n"


def _spec(count: int, **steps: Any) -> str:
    spec = {
        "extract": None,
        "members": [f"member_{index}" for index in range(1, count + 1)],
        "normalize": None,
        "schema": "screamingface.combine-spec.v1",
        "weights": None,
        **steps,
    }
    return json.dumps(spec)


def _context(texts: dict[int, str], **extra: Any) -> str:
    rows = [
        {"source_position": index, "source_name": f"member_{index}", "result": text}
        for index, text in texts.items()
    ]
    return json.dumps({"input": "q", "panel": json.dumps(rows), **extra})


def _statuses(outcome: Any) -> list[tuple[str, str, str | None]]:
    return [(m.member_id, m.status, m.reason) for m in outcome.evidence.members]


def test_concat_joins_only_the_members_that_answered() -> None:
    spec = _spec(
        3,
        reducer="concat",
        reduce={"op": "join@1", "args": {"label": True, "separator": _SEPARATOR}},
        select={"op": "all@1", "args": {}},
    )

    outcome = run(spec, _context({1: "A", 3: "C"}), registry=_BUILTINS)

    assert outcome.output == f"[member_1]\nA{_SEPARATOR}[member_3]\nC"
    assert outcome.evidence.chosen == ["member_1", "member_3"]
    assert _statuses(outcome)[1] == ("member_2", "fail", "missing")


def _rank(k: int) -> str:
    return _spec(
        3,
        reducer="rank",
        extract={"op": "json_field@1", "args": {"path": "score"}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "scores@1", "args": {"source": "values"}},
        select={"op": "top_k@1", "args": {"k": k}},
    )


def test_rank_cuts_among_the_members_that_answered() -> None:
    texts = {1: '{"score": 3}', 3: '{"score": 5}'}

    outcome = run(_rank(2), _context(texts), registry=_BUILTINS)

    assert outcome.evidence.chosen == ["member_3", "member_1"]
    short = run(_rank(3), _context(texts), registry=_BUILTINS)
    assert (short.evidence.result.status, short.evidence.result.reason) == (
        "abstain",
        "cut_not_met",
    )


def test_filter_marks_only_the_members_that_answered() -> None:
    spec = _spec(
        4,
        reducer="filter",
        reduce={"op": "filter@1", "args": {"cmp": "ge", "key": "field:confidence", "value": 0.6}},
        select={"op": "kept@1", "args": {}},
    )
    texts = {1: '{"confidence": 0.9}', 2: '{"confidence": 0.2}', 4: '{"confidence": 0.7}'}

    outcome = run(spec, _context(texts), registry=_BUILTINS)

    assert outcome.evidence.chosen == ["member_1", "member_4"]
    assert [m.score for m in outcome.evidence.members] == [1.0, 0.0, None, 1.0]
    assert outcome.evidence.members[2].signals == {"field:confidence": None}


def test_argmax_by_cost_never_picks_a_missing_member() -> None:
    spec = _spec(
        3,
        reducer="pick",
        reduce={"op": "by_signal@1", "args": {"key": "cost_usd", "order": "min"}},
        select={"op": "best_holder@1", "args": {"order": "min"}},
    )

    def reader(sources: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
        # The missing member's call never answered, so the recorder has no cost for it.
        return {"member_1": {"cost_usd": 0.004}, "member_3": {"cost_usd": 0.002}}

    outcome = run(
        spec,
        _context({1: "A", 3: "C"}, sources=_sources(3)),
        registry=_BUILTINS,
        accounting=reader,
    )

    assert outcome.output == "C"
    assert outcome.evidence.members[1].signals == {"cost_usd": None}
