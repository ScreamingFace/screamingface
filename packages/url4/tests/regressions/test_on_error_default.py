"""Audit A8 — an explicit inner `;iteration.on_error=collect` beats the outer policy.

Spec B §5.3.6: `collect` is the default policy. When a reduce-over-iteration merges
its inner and outer directives, the merge must tell an explicit inner `collect`
from no inner policy, or the outer policy wins by mistake. The parser tracks which
directive fields were GIVEN for that merge; the public `IterationDirectives` keeps
`on_error="collect"` as its plain default.
Report: docs/spec/2026-10-09-url4-audit/report.md §4.A (A8).
"""

from __future__ import annotations

from url4 import build, render
from url4.core.nodes import Iteration, IterationDirectives, Url
from url4.core.parser import IterationEnvelope, decode_envelope


def test_A8_the_default_policy_is_collect() -> None:
    assert IterationDirectives().on_error == "collect"


def test_A8_explicit_inner_collect_wins_over_the_outer_policy() -> None:
    env = decode_envelope(
        "(https://a.io*(/p($item)!x)!'per';iteration.on_error=collect)!'all';iteration.on_error=fail"
    )
    assert isinstance(env, IterationEnvelope)
    assert env.directives.on_error == "collect"


def test_A8_an_absent_inner_policy_takes_the_outer_one() -> None:
    env = decode_envelope("(https://a.io*(/p($item)!x)!'per')!'all';iteration.on_error=fail")
    assert isinstance(env, IterationEnvelope)
    assert env.directives.on_error == "fail"


def test_A8_explicit_collect_and_the_default_are_one_tree_and_one_text() -> None:
    explicit = build("https://a.io*(/p($item)!x)!'per';iteration.on_error=collect")
    implicit = build("https://a.io*(/p($item)!x)!'per'")
    assert explicit == implicit
    assert render(explicit) == render(implicit)


def test_A8_a_hand_built_collect_tree_renders_and_round_trips() -> None:
    tree = Iteration(
        collection=Url("https://a.io"),
        body="/p($item)!x",
        intent="'per'",
        directives=IterationDirectives(concurrency=4, on_error="collect"),
    )
    text = render(tree)
    assert "on_error" not in text
    assert build(text) == tree
