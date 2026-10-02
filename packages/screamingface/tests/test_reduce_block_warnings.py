"""An sf.Reduce block warns like a named reducer (OME-1289, BK#14 and U1 parity).

WHY these are guards: ``_reducer_synthesizer`` runs the duplicate-members check for every
``Reducer``, and ``sf.Reduce`` is a ``Reducer``. ``FixedSeedSittingWarning`` reads only the
Candidate's parameter assignments. So the block form needs no code of its own, and these tests
pass at once. They stop a later change from keying a warning on the synthesizer's class.
"""

from __future__ import annotations

import functools
import warnings
from collections.abc import Callable

import pytest
from _reducer_fixtures import FixtureVote, engine_operators, fixture_operators
from test_fixed_seed_sitting_warning import _MODEL, _run_sync
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.reducer import Reducer

_NUMERIC = sf.Extract("last_number", normalize="numeric")


def _vote() -> sf.Vote:
    return sf.Vote(extract="last_number", normalize="numeric")


def _plurality() -> sf.Reduce:
    return sf.Reduce("plurality", extract=_NUMERIC)


def _median() -> sf.Reduce:
    return sf.Reduce("median", extract=sf.Extract("last_number"))


def _weighted() -> sf.Reduce:
    return sf.Reduce("weighted", extract=_NUMERIC, weights=[1, 2, 3])


def _duplicates(synthesizer: Reducer) -> list[warnings.WarningMessage]:
    fusion = sf.Fusion(["provider/a", "provider/a", "provider/b"], synthesizer=synthesizer)
    with pytest.warns(sf.DuplicateMembersWarning) as recorded:
        compile_candidate(fusion, operators=engine_operators())
    return list(recorded)


@functools.cache
def _vote_warning_text() -> str:
    expected = _duplicates(_vote())
    assert len(expected) == 1
    expected_text = str(expected[0].message)
    assert expected_text.startswith(
        "Fusion 'a+a+b': members 1 and 2 send the same request to 'provider/a'; "
    )
    return expected_text


@pytest.mark.parametrize(
    "make",
    [_vote, _plurality, _median, _weighted, FixtureVote],
    ids=["vote", "reduce-plurality", "reduce-median", "reduce-weighted", "fixture-vote"],
)
def test_reduce_fusion_warns_on_duplicate_members_like_vote(make: Callable[[], Reducer]) -> None:
    expected_text = _vote_warning_text()

    recorded = _duplicates(make())

    assert len(recorded) == 1
    assert recorded[0].filename == __file__
    assert str(recorded[0].message) == expected_text


_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _duplicate_loop() -> sf.CorrectiveLoop:
    duplicated = sf.Fusion(["provider/a", "provider/a"], synthesizer=_plurality())
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


def test_reduce_fusion_in_a_corrective_loop_warns_once_and_never_on_recovery() -> None:
    with pytest.warns(sf.DuplicateMembersWarning) as recorded:
        compiled = _compile_loop()

    assert len(recorded) == 1

    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.DuplicateMembersWarning)
        python = sf.Url4(compiled).to_python()
        recovered = _candidate_from_url4(_linked(compiled))

    # WHY Vote and not Reduce: the named class wins when its own _from_spec accepts the spec.
    assert "sf.Vote(" in python
    assert recovered.kind == "corrective_loop"


def test_reduce_fusion_without_duplicates_does_not_warn() -> None:
    fusion = sf.Fusion(sf.samples("provider/a", 3), synthesizer=_plurality())

    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.DuplicateMembersWarning)
        compile_candidate(fusion, operators=fixture_operators())


def test_reduce_synthesizer_warns_fixed_seed_like_vote() -> None:
    vote, vote_transport = _run_sync(
        sf.Fusion(sf.samples(_MODEL, 3), synthesizer=_vote()), answer_seed=7
    )
    block, block_transport = _run_sync(
        sf.Fusion(sf.samples(_MODEL, 3), synthesizer=_plurality()), answer_seed=7
    )

    assert len(vote) == len(block) == 1
    assert str(block[0].message) == str(vote[0].message)
    assert (
        "3 calls set their own seed: op_model_1 (opus answer), op_model_2 (opus answer), "
        "op_model_3 (opus answer)"
    ) in str(block[0].message)
    assert block[0].filename == vote[0].filename
    # WHY: a warning, not a refusal; both runs reached the transport.
    assert vote_transport.called and block_transport.called

    unseeded, _ = _run_sync(
        sf.Fusion(sf.samples(_MODEL, 3), synthesizer=_plurality()), answer_seed=None
    )
    assert unseeded == []
