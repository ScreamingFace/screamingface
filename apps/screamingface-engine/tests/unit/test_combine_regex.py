"""regex@1 reads one group from the last 1024 characters, under a static ReDoS ban (OME-1289).

FEATURE: an author names a regex; the engine runs it deterministically and fast.
STORY: as an author of a majority-vote Candidate, I read the answer from a labelled line such as
"Final: B", and a pattern that could freeze a worker is refused when the spec is checked.
RX#1 to RX#7 (RX-D1 to RX-D5) of the E4a gap-closure; unit 2.
"""

from __future__ import annotations

import dataclasses
import re
import re._parser as _sre  # type: ignore[import-not-found]
import sys
import time
from typing import Any

import pytest
from combine_golden_support import find, stage
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS, BUILTIN_REGISTRATIONS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.operators import _regex_ban
from screamingface_engine.combine.operators._regex_ban import backtracking_shape
from screamingface_engine.combine.ports import CombineError, SpecInvalid, StageResult
from screamingface_engine.combine.registry import OperatorRegistry

_REJECTED = [
    ("nested_quantifier", "(a+)+"),
    ("nested_quantifier", "(a*)*"),
    ("nested_quantifier", "(a+)*b"),
    ("nested_quantifier", r"(?:\d+,?)+"),
    ("nested_quantifier", "(?>a+)+"),
    ("quantified_alternation", "(a|aa)+"),
    ("quantified_alternation", "(x|xy)*"),
    ("quantified_alternation", "(?:ab|cd)+"),
    ("adjacent_overlap", r"\d*\d*"),
    ("adjacent_overlap", ".*.*"),
    ("adjacent_overlap", r"\w+\d+"),
    ("adjacent_overlap", r"\d*a?\d*"),
    ("adjacent_overlap", r"(\d*)\d*"),
    ("adjacent_overlap", "[a-z]+[A-Z]+"),
]
_ACCEPTED_TIMED = [
    (r"Final: (\w+)", "Final: " * 146 + "xx"),
    (r"ANSWER:\s*([A-Da-d])", "ANSWER:" + " " * 1017),
    (r"\\boxed\{([^{}]*)\}", "\\boxed{" * 146 + "x"),
    (r"answer is (\w+)", "answer is " * 102 + "!!!!"),
    (r'"answer":\s*"([^"]*)"', '"answer": "' + "a" * 1011),
    (r"(\d+(?:\.\d+)?)", "1." * 512),
    (r"#### (-?[0-9,]+)", "#### " + "1" * 1019),
    (r"(?P<ans>[A-D])\)", "A" * 1024),
]


def _args(pattern: Any, **more: Any) -> dict[str, Any]:
    return {"pattern": pattern, **more}


def _check(args: dict[str, Any]) -> None:
    find("regex@1").check_args(args)


def _builtin_run(spec: dict[str, Any], texts: list[str]) -> CombineOutcome:
    return run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)


def _voted(value: str) -> StageResult:
    return StageResult(value, "voted")


# --- RX#1: the ban ---------------------------------------------------------------------------


def test_regex_parse_tree_is_the_pinned_stdlib_shape() -> None:
    assert sys.version_info[:2] in ((3, 12), (3, 13))
    expected = {
        "(a|aa)+": (
            "[(MAX_REPEAT, (1, MAXREPEAT, [(SUBPATTERN, (1, 0, 0, [(LITERAL, 97), "
            "(BRANCH, (None, [[], [(LITERAL, 97)]]))]))]))]"
        ),
        "(x|y)*": (
            "[(MAX_REPEAT, (0, MAXREPEAT, [(SUBPATTERN, (1, 0, 0, "
            "[(IN, [(LITERAL, 120), (LITERAL, 121)])]))]))]"
        ),
        r"\d*a?\d*": (
            "[(MAX_REPEAT, (0, MAXREPEAT, [(IN, [(CATEGORY, CATEGORY_DIGIT)])])), "
            "(MAX_REPEAT, (0, 1, [(LITERAL, 97)])), "
            "(MAX_REPEAT, (0, MAXREPEAT, [(IN, [(CATEGORY, CATEGORY_DIGIT)])]))]"
        ),
    }
    for pattern, tree in expected.items():
        assert repr(list(_sre.parse(pattern, 0).data)) == tree, pattern


@pytest.mark.parametrize(("shape", "pattern"), _REJECTED)
def test_backtracking_shapes_are_rejected(shape: str, pattern: str) -> None:
    assert backtracking_shape(pattern) == shape
    with pytest.raises(SpecInvalid) as raised:
        _check(_args(pattern))
    assert shape in str(raised.value)
    assert pattern not in str(raised.value)


def test_category_pairs_called_disjoint_share_no_code_point() -> None:
    sources = _regex_ban._CATEGORY_SOURCE
    compiled = {name: re.compile(source) for name, source in sources.items()}
    pairs = [tuple(sorted(pair)) for pair in _regex_ban._DISJOINT]
    assert all(len(pair) == 2 for pair in pairs)
    for code in range(0x110000):
        char = chr(code)
        hits = {name for name, pattern in compiled.items() if pattern.fullmatch(char)}
        for first, second in pairs:
            assert not (first in hits and second in hits), (first, second, hex(code))


@pytest.mark.parametrize(
    "pattern",
    ["(x|y)*", r"\s*(\w+)", "[a-z]+[0-9]+", r"\d+\s*\.", "a++", r"Final: (\w+)"],
)
def test_acceptance_decisions_are_pinned(pattern: str) -> None:
    # (x|y)* is a character set to sre (F4); a quadratic scan is accepted on purpose (F9).
    assert backtracking_shape(pattern) is None


@pytest.mark.parametrize(("pattern", "text"), _ACCEPTED_TIMED)
def test_accepted_patterns_finish_under_5ms_on_worst_input(pattern: str, text: str) -> None:
    assert len(text) <= 1024
    _check(_args(pattern))
    best = float("inf")
    for _ in range(5):
        started = time.perf_counter()
        stage("regex@1", text, _args(pattern))
        best = min(best, time.perf_counter() - started)
    assert best < 0.005, f"{pattern} took {best:.5f}s"


# --- RX#2: the args --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        _args("("),
        _args(""),
        _args("a" * 257),
        _args(5),
        {"pattern": "a", "flags": "i"},
        {"group": 0},
        _args("a", ignore_case="yes"),
        _args("a", occurrence="middle"),
    ],
    ids=[
        "does-not-compile",
        "empty",
        "too-long",
        "not-a-string",
        "unknown-key",
        "no-pattern",
        "ignore-case-not-bool",
        "occurrence-unknown",
    ],
)
def test_regex_pattern_that_does_not_compile_is_spec_invalid(args: dict[str, Any]) -> None:
    with pytest.raises(SpecInvalid):
        _check(args)


def test_regex_spec_invalid_is_raised_before_any_member_is_read() -> None:
    def crash(text: str, args: Any, /) -> StageResult:
        raise AssertionError("a member was read")

    descriptors = tuple(
        dataclasses.replace(d, run=crash) if d.id == "regex@1" else d for d in BUILTIN_REGISTRATIONS
    )
    spec = vote_spec(
        2,
        extract={"op": "regex@1", "args": _args("(")},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context_text(["a", "b"]), registry=OperatorRegistry(descriptors))
    assert caught.value.code == "combine_spec_invalid"


# --- RX#3 ------------------------------------------------------------------------------------


def test_regex_group_must_exist() -> None:
    for group in (2, "name", True, -1):
        with pytest.raises(SpecInvalid):
            _check(_args(r"(\w+)", group=group))
    _check(_args(r"(?P<ans>\w+)", group="ans"))
    _check(_args(r"(\w+)", group=0))
    _check(_args(r"(\w+)", group=1))


# --- RX#4 to RX#6 ----------------------------------------------------------------------------

_FINAL = _args(r"Final: (\w+)", group=1)


def _final_vote(count: int) -> dict[str, Any]:
    return vote_spec(
        count,
        extract={"op": "regex@1", "args": _FINAL},
        normalize={"op": "text@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )


def test_regex_takes_last_match_group_by_default() -> None:
    assert stage("regex@1", "Final: A\nFinal: B", _FINAL) == _voted("B")
    assert stage("regex@1", "Final: A\nFinal: B", {**_FINAL, "occurrence": "first"}) == _voted("A")
    texts = ["thinking... Final: B", "Final: b", "Final: c"]
    outcome = _builtin_run(_final_vote(3), texts)
    assert outcome.output == texts[0]
    evidence = outcome.evidence
    assert [(row.value, row.holders) for row in evidence.tally or []] == [
        ("b", ["member_1", "member_2"]),
        ("c", ["member_3"]),
    ]


def test_regex_no_match_is_fail_no_match() -> None:
    assert stage("regex@1", "no marker", _FINAL) == StageResult(None, "no_match")
    outcome = _builtin_run(_final_vote(3), ["Final: A", "nothing here", "Final: A"])
    rows = outcome.evidence.members
    assert (rows[1].status, rows[1].reason) == ("fail", "no_match")
    assert outcome.evidence.dropped == 1
    assert outcome.evidence.result.status == "answered"


def test_regex_scans_only_last_1024_characters() -> None:
    args = _args(r"Final: ([A-Z])", group=1)
    assert stage("regex@1", "Final: A" + "x" * 1024, args) == StageResult(None, "no_match")
    assert stage("regex@1", "Final: A" + "x" * 1016, args) == _voted("A")
    assert stage("regex@1", "Final: AB" + "x" * 1016, args) == StageResult(None, "no_match")


# --- RX#7 ------------------------------------------------------------------------------------


def test_regex_unicode_rules_are_pinned() -> None:
    assert stage("regex@1", "name \u00dc", _args(r"(\w+)$", group=1)) == _voted("\u00dc")
    assert stage("regex@1", "total \uff11\uff12", _args(r"(\d+)", group=1)) == _voted(
        "\uff11\uff12"
    )
    ignore = {"ignore_case": True, "group": 1}
    assert stage("regex@1", "FINAL: B", _args("final: (b)", **ignore)) == _voted("B")
    assert stage("regex@1", "\u00dc", _args("(\u00fc)", **ignore)) == _voted("\u00dc")
