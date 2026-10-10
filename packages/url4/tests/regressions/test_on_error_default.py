"""Audit A8 — an explicit `;iteration.on_error=collect` is not the same as "not given".

Spec B §5.3.6: `collect` is the default policy. The directive must still tell an
explicit `collect` from an absent one, so an explicit inner policy wins over the
outer one when the two merge, and render writes back what the author wrote.
Report: docs/spec/2026-10-09-url4-audit/report.md §4.A (A8).
"""

from __future__ import annotations

from url4 import build, render
from url4.core.nodes import Iteration, IterationDirectives
from url4.core.parser import IterationEnvelope, decode_envelope


def test_A8_no_directive_means_not_given_and_the_policy_is_collect() -> None:
    directives = IterationDirectives()
    assert directives.on_error is None
    assert directives.on_error_policy == "collect"


def test_A8_explicit_inner_collect_wins_over_the_outer_policy() -> None:
    env = decode_envelope(
        "(https://a.io*(/p($item)!x)!'per';iteration.on_error=collect)!'all';iteration.on_error=fail"
    )
    assert isinstance(env, IterationEnvelope)
    assert env.directives.on_error_policy == "collect"


def test_A8_an_absent_inner_policy_takes_the_outer_one() -> None:
    env = decode_envelope("(https://a.io*(/p($item)!x)!'per')!'all';iteration.on_error=fail")
    assert isinstance(env, IterationEnvelope)
    assert env.directives.on_error == "fail"


def test_A8_render_keeps_the_canonical_text_for_an_explicit_collect() -> None:
    # The canonical text omits the default policy, explicit or not, so canonical
    # bytes (and the benchmark hashes pinned on them) do not change.
    explicit = build("https://a.io*(/p($item)!x)!'per';iteration.on_error=collect")
    implicit = build("https://a.io*(/p($item)!x)!'per'")
    assert explicit == implicit  # a parse tree holds the settled directives
    assert isinstance(explicit, Iteration) and explicit.directives.on_error_policy == "collect"
    assert render(explicit) == render(implicit)


def test_A8_render_writes_no_policy_when_none_was_given() -> None:
    tree = build("https://a.io*(/p($item)!x)!'per'")
    assert isinstance(tree, Iteration)
    assert tree.directives.on_error is None
    assert "on_error" not in render(tree)
