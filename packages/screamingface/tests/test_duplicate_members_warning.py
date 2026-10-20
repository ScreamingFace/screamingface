"""A reducer Fusion warns when two direct Model members send the same request (OME-1289, SM-5)."""

from __future__ import annotations

import warnings

import pytest
from _nodes import fusion_node
from _reducer_fixtures import FixtureVote, fixture_operators
from url4 import expr, render, src, text

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.policy import DEFAULT_ANSWER_PROMPT
from screamingface._evaluation.url4 import _candidate_from_url4


def _compile(recipe: sf.Recipe) -> None:
    compile_candidate(recipe, operators=fixture_operators())


def test_duplicate_members_in_reducer_fusion_warn() -> None:
    fusion = fusion_node(["provider/a", "provider/a", "provider/b"], FixtureVote())

    with pytest.warns(
        sf.DuplicateMembersWarning, match=r"members 1 and 2 send the same request to 'provider/a'"
    ) as recorded:
        _compile(fusion)

    assert len(recorded) == 1
    assert "sf.samples()" in str(recorded[0].message)
    assert isinstance(recorded[0].message, sf.EvaluationWarning)
    assert recorded[0].filename == __file__


def test_three_equal_members_name_all_three_positions() -> None:
    fusion = fusion_node(["provider/a"] * 3, FixtureVote())

    with pytest.warns(sf.DuplicateMembersWarning, match=r"members 1, 2 and 3 send the same"):
        _compile(fusion)


def test_two_groups_of_duplicates_warn_once_each() -> None:
    fusion = fusion_node(["provider/a", "provider/b", "provider/a", "provider/b"], FixtureVote())

    with pytest.warns(sf.DuplicateMembersWarning) as recorded:
        _compile(fusion)

    assert sorted(
        str(item.message).split("members ")[1].split(" send")[0] for item in recorded
    ) == [
        "1 and 3",
        "2 and 4",
    ]


@pytest.mark.parametrize(
    "fusion",
    [
        fusion_node(sf.samples("provider/a", 3), FixtureVote()),
        fusion_node(
            [sf.Model("provider/a", prompt="en"), sf.Model("provider/a", prompt="fr")],
            FixtureVote(),
        ),
        fusion_node(
            [sf.Model("provider/a", params={"top_p": 0.1}), sf.Model("provider/a")],
            FixtureVote(),
        ),
        # A Model synthesizer is not a reducer Fusion: the guard is for reducers only.
        sx.Fanout(["provider/a", "provider/a"]) >> sx.Synthesize("provider/s"),
        # Recipe members are skipped, so two equal nested Fusions do not warn.
        fusion_node(
            [
                sx.Fanout(["provider/a", "provider/b"]) >> sx.Synthesize("provider/s"),
                sx.Fanout(["provider/a", "provider/b"]) >> sx.Synthesize("provider/s"),
            ],
            FixtureVote(),
        ),
    ],
    ids=["samples", "prompts", "params", "model-synthesizer", "nested-fusions"],
)
def test_distinct_members_and_non_reducer_fusions_do_not_warn(fusion: sf.Fusion) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.DuplicateMembersWarning)
        _compile(fusion)


_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _duplicate_loop() -> sf.CorrectiveLoop:
    duplicated = fusion_node(["provider/a", "provider/a"], FixtureVote())
    return sf.CorrectiveLoop([duplicated, "provider/d"], judge="provider/j", max_rounds=2)


def _compile_loop() -> str:
    return compile_candidate(
        _duplicate_loop(), check_surface=_SURFACE, operators=fixture_operators()
    ).url4


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def test_url4_recovery_never_repeats_the_warning() -> None:
    with pytest.warns(sf.DuplicateMembersWarning) as recorded:
        compiled = _compile_loop()

    assert len(recorded) == 1  # once per fusion object, not once per round

    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.DuplicateMembersWarning)
        python = sf.Url4(compiled).to_python()
        recovered = _candidate_from_url4(_linked(compiled))

    assert "Fusion" in python
    assert recovered.kind == "corrective_loop"


def _pair(first: sf.Model, second: sf.Model) -> sf.Fusion:
    return fusion_node([first, second], FixtureVote())


@pytest.mark.parametrize(
    "fusion",
    [
        _pair(sf.Model("provider/a"), sf.Model("provider/a", prompt=DEFAULT_ANSWER_PROMPT)),
        _pair(sf.Model("/provider/a"), sf.Model("provider/a")),
        _pair(
            sf.Model("provider/a", params={"temperature": 0.7}),
            sf.Model("provider/a", params={"temperature": "0.7"}),
        ),
        _pair(
            sf.Model("provider/a", params={"top_p": 0.9, "max_tokens": 8}),
            sf.Model("provider/a", params={"max_tokens": 8, "top_p": 0.9}),
        ),
        _pair(sf.Model("provider/a", name="x"), sf.Model("provider/a", name="y")),
    ],
    ids=["default-prompt", "leading-slash", "param-spelling", "param-order", "names"],
)
def test_spellings_that_send_the_same_request_warn(fusion: sf.Fusion) -> None:
    with pytest.warns(sf.DuplicateMembersWarning, match="members 1 and 2"):
        _compile(fusion)


def test_a_bool_param_is_not_the_integer_it_resembles() -> None:
    fusion = _pair(
        sf.Model("provider/a", params={"max_tokens": 1}),
        sf.Model("provider/a", params={"max_tokens": True}),
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.DuplicateMembersWarning)
        _compile(fusion)
