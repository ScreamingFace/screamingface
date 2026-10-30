"""The verbalized source: the last match, the number, the window, the pattern checks (E4b part 3).

FEATURE: ``verbalized`` reads the number that a member states in its text, for example
``Confidence: 90``, and a vote weights each answer by it (E4b part 3, unit 2; VB#1-7, VB#9, VB#10).
STORY: as a researcher, I ask every member for a confidence and the engine reads the last one
the member wrote, as an ASCII decimal, and gives it the weight of the vote.
INVARIANT defended: the group of the LAST match in the last 65,536 characters is the value; only
an ASCII decimal number counts (no exponent, NaN, inf, comma or fullwidth digit); a pattern has
exactly one capture group; RE2 runs in linear time on a hostile text; a text over 1 MiB reads no
number; a zero or negative number leaves the member out of the vote (weight rule of E4a).
"""

from __future__ import annotations

import math
import time
from typing import Any

import pytest
import re2
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.operators.extract import check_signal_pattern, verbalized_value
from screamingface_engine.combine.ports import CombineError, SpecInvalid

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


def _args(pattern: str, **more: Any) -> dict[str, Any]:
    return {"pattern": pattern, **more}


def _run(spec: dict[str, Any], texts: list[str]) -> Any:
    return run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)


# --- VB#1: the group of the last match is the number ------------------------------------------


def test_verbalized_takes_the_group_of_the_last_match() -> None:
    args = _args(CONF_PATTERN)
    assert verbalized_value("Answer: 12\nConfidence: 90", args) == 90.0
    assert verbalized_value("Confidence: 40 ... on reflection, Confidence: 75", args) == 75.0
    assert verbalized_value("Confidence:  42  ", _args("Confidence:(.*)")) == 42.0
    assert verbalized_value("Score: -3", _args("Score: (\\S+)")) == -3.0
    assert verbalized_value("Confidence: 87.5", _args("Confidence: (\\S+)")) == 87.5


# --- VB#2: no match gives no number and no weight ---------------------------------------------


def test_verbalized_with_no_match_is_none() -> None:
    args = _args(CONF_PATTERN)
    assert verbalized_value("no confidence here", args) is None
    assert verbalized_value("", args) is None

    outcome = _run(
        conf_weighted_vote(),
        ["no line\nA", "Confidence: 60\nB", "Confidence: 30\nA"],
    )
    members = outcome.evidence.members
    assert members[0].signals == {"conf": None}
    assert members[0].weight is None
    assert [(row.value, row.score, row.holders) for row in outcome.evidence.tally] == [
        ("b", 60.0, ["member_2"]),
        ("a", 30.0, ["member_3"]),
    ]
    assert outcome.evidence.chosen == ["member_2"]


# --- VB#3: only an ASCII decimal number is a value --------------------------------------------


def test_verbalized_non_number_group_is_none() -> None:
    assert verbalized_value("Confidence: high", _args("Confidence: (\\w+)")) is None

    refused = ["1e9", "NaN", "inf", "9,5", "5.", ".5", "0x10", "１２", "9" * 400]
    for group in refused:
        assert verbalized_value(f"Confidence: {group}", _args("Confidence: (\\S+)")) is None, group

    accepted = {"+5": 5.0, "-2.50": -2.5, "007": 7.0, "-0": 0.0}
    for group, value in accepted.items():
        number = verbalized_value(f"Confidence: {group}", _args("Confidence: (\\S+)"))
        assert number == value, group
    zero = verbalized_value("Confidence: -0", _args("Confidence: (\\S+)"))
    assert zero is not None and math.copysign(1.0, zero) == 1.0


# --- VB#4 (engine half): a bad pattern or a group count other than one is refused -------------


def test_verbalized_refuses_a_bad_pattern_or_a_group_count_other_than_one() -> None:
    # Positive first: a one-group pattern and an extra non-capturing group are accepted.
    assert check_signal_pattern({"pattern": CONF_PATTERN}) is None
    assert check_signal_pattern({"pattern": "(?P<n>[0-9]+)(?:x)", "ignore_case": True}) is None

    refused: list[dict[str, Any]] = [
        {"pattern": "Confidence: [0-9]+"},
        {"pattern": "(a)(b)"},
        {"pattern": "("},
        {"pattern": "a" * 257},
        {"pattern": ""},
        {"pattern": "(a)", "group": 1},
        {},
        {"pattern": "(a)", "ignore_case": "yes"},
    ]
    for args in refused:
        with pytest.raises(SpecInvalid):
            check_signal_pattern(args)

    with pytest.raises(CombineError) as caught:
        _run(conf_weighted_vote(pattern="ZQ(a)(b)"), ["Confidence: 90\nA"])
    assert caught.value.code == "combine_spec_invalid"
    assert "ZQ" not in str(caught.value)


# --- VB#5: only the last 65,536 characters are read, under the 1 MiB cap ----------------------


def test_verbalized_reads_only_the_last_64_kib_under_the_read_cap() -> None:
    line = "Confidence: 90"
    args = _args(CONF_PATTERN)
    assert len(line) == 14
    # WHY the three lengths: 65,536 characters keep the line; one more drops its first letter.
    assert verbalized_value(line + "x" * (65_536 - 14), args) == 90.0
    assert verbalized_value(line + "x" * (65_536 - 13), args) is None
    assert verbalized_value(line + "x" * 65_536, args) is None

    outcome = _run(
        conf_weighted_vote(),
        ["x" * (1024 * 1024) + "\nConfidence: 90\nA", "Confidence: 60\nB", "Confidence: 30\nA"],
    )
    member_1 = outcome.evidence.members[0]
    assert member_1.signals == {"conf": None}
    assert member_1.status == "fail"
    assert member_1.reason == "too_large"
    assert outcome.evidence.chosen == ["member_2"]


# --- VB#6: a lone surrogate reads as U+FFFD and never raises ----------------------------------


def test_verbalized_survives_a_lone_surrogate() -> None:
    assert verbalized_value("\ud800 Confidence: 75", _args(CONF_PATTERN)) == 75.0
    assert verbalized_value("Confidence: \ud800", _args("Confidence: (.)")) is None


# --- VB#7 (engine half): ignore_case is a flag of the pattern ---------------------------------


def test_verbalized_ignore_case() -> None:
    assert verbalized_value("confidence: 90", _args(CONF_PATTERN, ignore_case=True)) == 90.0
    assert verbalized_value("confidence: 90", _args(CONF_PATTERN)) is None
    assert verbalized_value("confidence: 90", _args(CONF_PATTERN, ignore_case=False)) is None


# --- VB#9: a zero or negative number leaves the member out of the vote -----------------------


def test_verbalized_zero_weight_leaves_the_member_out() -> None:
    outcome = _run(
        conf_weighted_vote(4, pattern="Confidence: (-?[0-9]+)"),
        ["Confidence: 0\nA", "Confidence: 60\nB", "Confidence: -5\nA", "Confidence: 30\nA"],
    )

    members = outcome.evidence.members
    assert [member.weight for member in members] == [None, 60.0, None, 30.0]
    assert [member.signals for member in members] == [
        {"conf": 0.0},
        {"conf": 60.0},
        {"conf": -5.0},
        {"conf": 30.0},
    ]
    assert [(row.value, row.score, row.holders) for row in outcome.evidence.tally] == [
        ("b", 60.0, ["member_2"]),
        ("a", 30.0, ["member_4"]),
    ]
    assert outcome.evidence.chosen == ["member_2"]
    assert outcome.output == "Confidence: 60\nB"


# --- VB#10: the scan is linear and fits a generous CPU bound ----------------------------------

# WHY N = 1000: the largest repeat bound in {1000, 900, 600, 300} whose RE2 program is between
# 1000 and 5000 instructions (programsize 2017 at N = 1000); the scan limit of 5000 holds.
_CPU_PATTERN = "Confidence: ([0-9]{1,1000})"


def test_verbalized_scan_stays_under_a_generous_cpu_bound() -> None:
    assert 1000 <= re2.compile(_CPU_PATTERN).programsize <= 5000
    text = "Confidence: x" * 5_042 + "Confidence: 7"
    assert len(text) == 65_559

    best = float("inf")
    value: float | None = None
    for _ in range(3):
        started = time.perf_counter()
        value = verbalized_value(text, _args(_CPU_PATTERN))
        best = min(best, time.perf_counter() - started)
    assert value == 7.0
    assert best < 0.5, f"verbalized took {best:.3f}s"
