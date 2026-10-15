"""Declared signals in the combine core: the spec parse, the plan check, the evidence (E4b part 3).

FEATURE: a spec names signal sources in ``signals`` and reads them by name (E4b part 3, unit 2;
DS#3, DS#10-13 of the declared-signals PRD).
STORY: as a researcher, a vote weights each answer by the confidence its member states, and the
evidence records every declared number for every member, read by a rule or not.
INVARIANT defended: a name the spec does not declare is refused at plan time, before any member
text is read (contracts C1); operators see only the key they read (E2); the evidence records every
declared name for every member; a member that a quorum panel left out gets None for every name;
the engine never echoes a declared name in a refusal message.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from combine_signal_support import argmax_spec, costs, filter_spec, sources
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import SignalRecord
from screamingface_engine.combine.ports import CombineError
from screamingface_engine.combine.spec import parse_spec

CONF_PATTERN = "Confidence: ([0-9]+)"
CONF_ENTRY = {"source": "verbalized", "pattern": CONF_PATTERN}


def real_vote(member_count: int = 3, **overrides: Any) -> dict[str, Any]:
    """A vote over the built-in operators (last line, text, mode, first holder)."""
    spec: dict[str, Any] = {
        "extract": {"op": "last_line@1", "args": {}},
        "normalize": {"op": "text@1", "args": {}},
        "reduce": {"op": "mode@1", "args": {}},
        "select": {"op": "first_holder@1", "args": {}},
    }
    spec.update(overrides)
    return vote_spec(member_count, **spec)


def conf_weighted_vote(member_count: int = 3, pattern: str = CONF_PATTERN) -> dict[str, Any]:
    return real_vote(
        member_count,
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": "conf"},
        signals={"conf": {"source": "verbalized", "pattern": pattern}},
    )


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


def _code(spec: dict[str, Any]) -> tuple[str, str]:
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["A", "B", "C"]), registry=BUILTIN_OPERATORS)
    return caught.value.code, str(caught.value)


# --- DS#3: an undeclared logprob_mean is refused everywhere (CHAR) ----------------------------


@pytest.mark.parametrize(
    "spec",
    [
        real_vote(
            3,
            reduce={"op": "weighted_mode@1", "args": {}},
            select={"op": "max_weight_holder@1", "args": {}},
            weights={"signal": "logprob_mean"},
        ),
        argmax_spec(3, "logprob_mean", "max"),
        filter_spec(3, {"key": "logprob_mean", "cmp": "ge", "value": 0.5}),
    ],
)
def test_engine_refuses_undeclared_logprob_mean_everywhere(spec: dict[str, Any]) -> None:
    code, message = _code(spec)

    assert code == "combine_spec_invalid"
    assert "logprob_mean" not in message


# --- DS#10: the spec parses the signals map and refuses an undeclared read --------------------


def test_engine_parses_signals_and_refuses_an_undeclared_read() -> None:
    # Positive first: a declared read parses and runs.
    parsed = parse_spec(spec_text(conf_weighted_vote()))
    assert parsed.signals is not None
    assert parsed.signals["conf"].pattern == CONF_PATTERN
    assert parsed.signals["conf"].source == "verbalized"
    outcome = run(
        spec_text(conf_weighted_vote()),
        context_text(["Confidence: 90\nA", "Confidence: 60\nB", "Confidence: 30\nA"]),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.output == "Confidence: 90\nA"

    undeclared = [
        {**conf_weighted_vote(), "weights": {"signal": "zq_undeclared"}},
        {**argmax_spec(3, "zq_undeclared", "max"), "signals": {"conf": CONF_ENTRY}},
        {
            **filter_spec(3, {"key": "zq_undeclared", "cmp": "ge", "value": 0.5}),
            "signals": {"conf": CONF_ENTRY},
        },
        argmax_spec(3, "zq_undeclared", "max"),
        filter_spec(3, {"key": "zq_undeclared", "cmp": "ge", "value": 0.5}),
    ]
    for spec in undeclared:
        code, message = _code(spec)
        assert code == "combine_spec_invalid"
        assert "zq_undeclared" not in message

    bad_declarations: list[Any] = [
        {"Conf": CONF_ENTRY},
        {"cost_usd": CONF_ENTRY},
        {"logprob_x": CONF_ENTRY},
        {f"n{index}": CONF_ENTRY for index in range(9)},
        {},
        None,
        {"conf": {"source": "consistency"}},
        {"conf": {**CONF_ENTRY, "flags": 1}},
    ]
    for declaration in bad_declarations:
        code, _ = _code({**conf_weighted_vote(), "signals": declaration})
        assert code == "combine_spec_invalid"


# --- DS#11: every declared name is recorded for every member ----------------------------------


def test_engine_records_every_declared_name_for_every_member() -> None:
    spec = {
        **argmax_spec(3, "cost_usd", "min"),
        "signals": {"conf": CONF_ENTRY, "conf2": CONF_ENTRY},
    }
    outcome = run(
        spec_text(spec),
        context_text(["Confidence: 90", "Confidence: 60", "no number"], sources=sources(3)),
        registry=BUILTIN_OPERATORS,
        accounting=costs(0.004, 0.001, 0.002),
    )

    evidence = outcome.evidence
    members = evidence.members
    assert outcome.output == "Confidence: 60"
    assert evidence.chosen == ["member_2"]
    assert evidence.signal == SignalRecord(key="cost_usd", order="min")
    assert [member.signals for member in members] == [
        {"cost_usd": 0.004, "conf": 90.0, "conf2": 90.0},
        {"cost_usd": 0.001, "conf": 60.0, "conf2": 60.0},
        {"cost_usd": 0.002, "conf": None, "conf2": None},
    ]
    assert list(members[0].signals) == ["cost_usd", "conf", "conf2"]
    assert [member.score for member in members] == [0.004, 0.001, 0.002]


# --- DS#12: the evidence carries the declared map as the spec wrote it -----------------------


def test_evidence_declared_equals_the_spec_signals() -> None:
    signals = {
        "conf": CONF_ENTRY,
        "level": {"source": "verbalized", "pattern": "Level: ([0-9]+)", "ignore_case": True},
    }
    texts = ["Confidence: 90\nLEVEL: 3\nA", "Confidence: 60\nlevel: 4\nB", "Confidence: 30\nA"]
    outcome = run(
        spec_text(real_vote(3, signals=signals)), context_text(texts), registry=BUILTIN_OPERATORS
    )

    assert outcome.output == texts[0]
    evidence = outcome.evidence
    assert evidence.declared == signals
    dump = evidence.model_dump(by_alias=True)
    assert dump["declared"] == signals
    assert list(dump).index("declared") == list(dump).index("signal") + 1
    assert [member.signals for member in evidence.members] == [
        {"conf": 90.0, "level": 3.0},
        {"conf": 60.0, "level": 4.0},
        {"conf": 30.0, "level": None},
    ]
    assert evidence.signal is None

    plain = run(spec_text(real_vote(3)), context_text(texts), registry=BUILTIN_OPERATORS)
    plain_dump = plain.evidence.model_dump(by_alias=True)
    assert "declared" not in plain_dump
    assert [member.signals for member in plain.evidence.members] == [{}, {}, {}]


# --- DS#13: an empty panel and a missing member get None for every declared name --------------


def test_empty_panel_and_missing_member_get_none_for_declared_names() -> None:
    spec = real_vote(3, signals={"conf": CONF_ENTRY})

    empty = run(spec_text(spec), _panel_context({}), registry=BUILTIN_OPERATORS)
    assert empty.output == ""
    assert empty.evidence.result.status == "abstain"
    assert empty.evidence.result.reason == "no_votes"
    assert [member.signals for member in empty.evidence.members] == [{"conf": None}] * 3
    assert empty.evidence.declared == {"conf": CONF_ENTRY}

    partial = run(
        spec_text(spec),
        _panel_context({1: "Confidence: 90\nA", 3: "Confidence: 30\nA"}),
        registry=BUILTIN_OPERATORS,
    )
    member_2 = partial.evidence.members[1]
    assert (member_2.status, member_2.reason) == ("fail", "missing")
    assert [member.signals for member in partial.evidence.members] == [
        {"conf": 90.0},
        {"conf": None},
        {"conf": 30.0},
    ]
    assert partial.output == "Confidence: 90\nA"
