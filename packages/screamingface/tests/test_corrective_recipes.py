"""CorrectiveLoop / SelfCorrective construction — the recipe-side contract.

FEATURE: benchmark-independent corrective loop (OME-796 / OME-828).
STORY: as a user, a malformed loop fails at construction — before any
benchmark fetch, compile, or paid call (fail-before-spend starts here).
"""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface import _surface as sx


def test_corrective_loop_normalizes_string_members_and_judge() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    assert [member.name for member in loop.members] == ["a", "b"]
    assert isinstance(loop.judge, sf.Model)
    assert loop.max_rounds == 3
    assert loop.name == "a+b"


def test_corrective_loop_accepts_an_explicit_name() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", name="panel")
    assert loop.name == "panel"


def test_corrective_loop_enforces_the_member_floor() -> None:
    # WHY 2: a corrective PANEL needs at least two drafts to select between —
    # one member is SelfCorrective's shape, not a degenerate panel.
    with pytest.raises(ValueError, match="at least 2 members"):
        sf.CorrectiveLoop(["prov/a"], judge="prov/j")


def test_corrective_loop_does_not_inherit_the_lanl_four_member_ceiling() -> None:
    loop = sf.CorrectiveLoop(
        ["prov/a", "prov/b", "prov/c", "prov/d", "prov/e"],
        judge="prov/j",
    )

    assert [member.name for member in loop.members] == ["a", "b", "c", "d", "e"]


def test_corrective_loop_requires_a_judge() -> None:
    with pytest.raises(TypeError):
        sf.CorrectiveLoop(["prov/a", "prov/b"])  # type: ignore[call-arg]


def test_max_rounds_is_a_positive_integer() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", max_rounds=0)
    with pytest.raises(TypeError, match="integer"):
        sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", max_rounds=2.5)  # type: ignore[arg-type]


def test_loops_are_root_only_recipes() -> None:
    # INVARIANT (root-only): inside a Fusion or Pipeline "the benchmark" is
    # undefined, so a nested loop is rejected at CONSTRUCTION — the earliest
    # possible fail-before-spend point.
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    with pytest.raises(TypeError, match="must be a model route or sf.Model"):
        _ = sx.Fanout([loop]) >> sx.Synthesize("prov/s")
    with pytest.raises(TypeError, match="must be a model route or sf.Model"):
        sf.Pipeline(("prov/a", loop))
    with pytest.raises(TypeError, match="must be a model route or sf.Model"):
        sf.CorrectiveLoop([loop, "prov/b"], judge="prov/j")
    with pytest.raises(TypeError, match="must be a model route or sf.Model"):
        sf.SelfCorrective(loop)  # type: ignore[arg-type]


def test_corrective_loop_accepts_composite_members() -> None:
    fusion = sx.Fanout(["prov/a", "prov/b"]) >> sx.Synthesize("prov/s")
    loop = sf.CorrectiveLoop([fusion, "prov/c"], judge="prov/j")
    assert loop.members[0] is fusion


def test_self_corrective_wraps_one_model() -> None:
    solo = sf.SelfCorrective("prov/a", max_rounds=2)
    assert isinstance(solo.member, sf.Model)
    assert solo.max_rounds == 2
    assert solo.name == "a"


def test_recipes_are_unhashable_like_their_siblings() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j")
    with pytest.raises(TypeError):
        hash(loop)


def test_reprs_read_as_constructors() -> None:
    loop = sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j", max_rounds=2)
    assert repr(loop).startswith("CorrectiveLoop(['a', 'b']")
    assert "max_rounds=2" in repr(loop)
    solo = sf.SelfCorrective("prov/a")
    assert repr(solo) == "SelfCorrective('a')"
