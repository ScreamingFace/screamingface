"""A reducer Fusion warns when two direct Model members send the same request (OME-1289, SM-5)."""

from __future__ import annotations

import warnings

import pytest
from _reducer_fixtures import FixtureVote, fixture_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


def _compile(recipe: sf.Recipe) -> None:
    compile_candidate(recipe, operators=fixture_operators())


def test_duplicate_members_in_reducer_fusion_warn() -> None:
    fusion = sf.Fusion(["provider/a", "provider/a", "provider/b"], synthesizer=FixtureVote())

    with pytest.warns(
        sf.DuplicateMembersWarning, match=r"members 1 and 2 send the same request to 'provider/a'"
    ) as recorded:
        _compile(fusion)

    assert len(recorded) == 1
    assert "sf.samples()" in str(recorded[0].message)
    assert isinstance(recorded[0].message, sf.EvaluationWarning)


def test_three_equal_members_name_all_three_positions() -> None:
    fusion = sf.Fusion(["provider/a"] * 3, synthesizer=FixtureVote())

    with pytest.warns(sf.DuplicateMembersWarning, match=r"members 1, 2 and 3 send the same"):
        _compile(fusion)


def test_two_groups_of_duplicates_warn_once_each() -> None:
    fusion = sf.Fusion(
        ["provider/a", "provider/b", "provider/a", "provider/b"], synthesizer=FixtureVote()
    )

    with pytest.warns(sf.DuplicateMembersWarning) as recorded:
        _compile(fusion)

    assert sorted(
        str(item.message).split("members ")[1].split(" send")[0] for item in recorded
    ) == [
        "1 and 3",
        "2 and 4",
    ]


def test_names_do_not_hide_a_duplicate() -> None:
    fusion = sf.Fusion(
        [sf.Model("provider/a", name="x"), sf.Model("provider/a", name="y")],
        synthesizer=FixtureVote(),
    )

    with pytest.warns(sf.DuplicateMembersWarning, match=r"members 1 and 2"):
        _compile(fusion)


@pytest.mark.parametrize(
    "fusion",
    [
        sf.Fusion(sf.samples("provider/a", 3), synthesizer=FixtureVote()),
        sf.Fusion(
            [sf.Model("provider/a", prompt="en"), sf.Model("provider/a", prompt="fr")],
            synthesizer=FixtureVote(),
        ),
        sf.Fusion(
            [sf.Model("provider/a", params={"top_p": 0.1}), sf.Model("provider/a")],
            synthesizer=FixtureVote(),
        ),
        # A Model synthesizer is not a reducer Fusion: the guard is for reducers only.
        sf.Fusion(["provider/a", "provider/a"], synthesizer="provider/s"),
        # Recipe members are skipped, so two equal nested Fusions do not warn.
        sf.Fusion(
            [
                sf.Fusion(["provider/a", "provider/b"], synthesizer="provider/s"),
                sf.Fusion(["provider/a", "provider/b"], synthesizer="provider/s"),
            ],
            synthesizer=FixtureVote(),
        ),
    ],
    ids=["samples", "prompts", "params", "model-synthesizer", "nested-fusions"],
)
def test_distinct_members_and_non_reducer_fusions_do_not_warn(fusion: sf.Fusion) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.DuplicateMembersWarning)
        _compile(fusion)
