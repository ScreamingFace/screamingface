"""The verified wire bytes of an ``expand.at_most_one=true`` panel (C19, test-plan row 178).

FEATURE: Router Recipe extension, contract C19. A marked member must reach a reader that
predates the mark as bytes that reader already accepts, so a mixed fleet can roll the new
reader out first.

WHY golden bytes: an isolated url4 install from ``455166b0d`` (before the mark existed)
accepted each of these 24 strings, as the work ledger records. That old reader does not run
here; these tests pin the bytes it accepted, so a change to any of them shows up as a
failure and calls for a new old-reader run before release.
"""

from __future__ import annotations

import itertools

import pytest

from url4 import Text, expr, render, src
from url4.core.grammar import parse
from url4.core.nodes import Expression, Url

_MEMBERS = {"zero": "https://none", "one": "https://one", "two": "https://two"}

# INVARIANT: the same order as _GOLDEN: panel, then guard, then quorum, then member body.
_CASES = list(itertools.product(("text", "broadcast"), ("required", "optional"), (3, 2), _MEMBERS))

_GOLDEN = (
    "(a=https://a, b=https://b, *m:https://none;required;expand.at_most_one=true)!'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://one;required;expand.at_most_one=true)!'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://two;required;expand.at_most_one=true)!'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://none;required;expand.at_most_one=true)!'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://one;required;expand.at_most_one=true)!'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://two;required;expand.at_most_one=true)!'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://none;optional;expand.at_most_one=true)!'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://one;optional;expand.at_most_one=true)!'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://two;optional;expand.at_most_one=true)!'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://none;optional;expand.at_most_one=true)!'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://one;optional;expand.at_most_one=true)!'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://two;optional;expand.at_most_one=true)!'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://none;required;expand.at_most_one=true)!*'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://one;required;expand.at_most_one=true)!*'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://two;required;expand.at_most_one=true)!*'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://none;required;expand.at_most_one=true)!*'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://one;required;expand.at_most_one=true)!*'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://two;required;expand.at_most_one=true)!*'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://none;optional;expand.at_most_one=true)!*'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://one;optional;expand.at_most_one=true)!*'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://two;optional;expand.at_most_one=true)!*'go';quorum=3",
    "(a=https://a, b=https://b, *m:https://none;optional;expand.at_most_one=true)!*'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://one;optional;expand.at_most_one=true)!*'go';quorum=2",
    "(a=https://a, b=https://b, *m:https://two;optional;expand.at_most_one=true)!*'go';quorum=2",
)


def _panel(panel: str, guard: str, quorum: int, case: str) -> Expression:
    """Two plain members and one marked member, built through the public builder."""
    member = src(
        Url(_MEMBERS[case]),
        name="m",
        expand=True,
        required=guard == "required",
        at_most_one=True,
    )
    return expr(
        src(Url("https://a"), name="a"),
        src(Url("https://b"), name="b"),
        member,
        intent=Text("go"),
        broadcast=panel == "broadcast",
        params=[("quorum", str(quorum))],
    )


def test_the_golden_set_covers_every_case_once() -> None:
    assert len(_CASES) == len(_GOLDEN) == 24
    assert len(set(_GOLDEN)) == 24


@pytest.mark.parametrize(
    ("case", "golden"),
    list(zip(_CASES, _GOLDEN, strict=True)),
    ids=["-".join(map(str, case)) for case in _CASES],
)
def test_the_builder_writes_the_verified_bytes(
    case: tuple[str, str, int, str], golden: str
) -> None:
    node = _panel(*case)
    assert render(node) == golden
    assert parse(golden) == node
