"""Drift guard for the logprob and entropy engine fixtures (E4b part 3, unit 4).

FEATURE: the Engine runs ten ``combine_contract/*.url4`` files verbatim (LP#7-13, EN#9-10). This
file builds each one with the SDK compiler and keeps the data files byte-identical to it.
STORY: as a maintainer, a change to the SDK compile of a logprob or entropy Fusion fails here,
not in a silent engine run.
INVARIANT defended: each fixture is the SDK compile of its builder below, plus one final newline.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_logprob_entropy_url4_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

_ALPHA = "openrouter/acme/alpha"
_BETA = "openrouter/acme/beta"
_GAMMA = "openrouter/acme/gamma"
_MEMBERS = [_ALPHA, _BETA, _GAMMA]
_WRITER = "openrouter/acme/writer"


def _pick(name: str, order: Literal["max", "min"] = "max") -> sf.Pick:
    return sf.Pick(by_signal=sf.signal(name), order=order)


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def logprob_pick_mean() -> str:
    return _compiled(
        sf.Fusion(_MEMBERS, signals={"lp": sf.Logprob("mean")}, synthesizer=_pick("lp"))
    )


def logprob_vote_prob() -> str:
    return _compiled(
        sx.Fanout(_MEMBERS, signals={"p": sf.Logprob("prob")}) >> sx.Vote(weights=sf.signal("p"))
    )


def logprob_filter_mean() -> str:
    fusion = sf.Fusion(
        _MEMBERS,
        signals={"lp": sf.Logprob("mean")},
        synthesizer=sf.Filter(where=sf.signal("lp") >= -0.5),
    )
    return _compiled(sf.Pipeline([fusion, _WRITER]))


def logprob_steer_filter() -> str:
    fusion = sf.Fusion(
        [_ALPHA],
        signals={"lp": sf.Logprob("mean")},
        synthesizer=sf.Filter(where=sf.signal("lp") >= -0.3),
    )
    return _compiled(sf.Pipeline([fusion, _WRITER]))


def logprob_samples_pick() -> str:
    return _compiled(
        sf.Fusion(
            sf.samples(_ALPHA, 3), signals={"lp": sf.Logprob("mean")}, synthesizer=_pick("lp")
        )
    )


def logprob_rank_mean() -> str:
    fusion = sf.Fusion(
        _MEMBERS,
        signals={"lp": sf.Logprob("mean")},
        synthesizer=sf.Rank(2, by_signal=sf.signal("lp")),
    )
    return _compiled(sf.Pipeline([fusion, _WRITER]))


def logprob_pick_sum() -> str:
    return _compiled(
        sf.Fusion([_ALPHA, _BETA], signals={"lp": sf.Logprob("sum")}, synthesizer=_pick("lp"))
    )


def logprob_filter_prob() -> str:
    fusion = sf.Fusion(
        _MEMBERS,
        signals={"p": sf.Logprob("prob")},
        synthesizer=sf.Filter(where=sf.signal("p") >= 0.8),
    )
    return _compiled(sf.Pipeline([fusion, _WRITER]))


def entropy_pick_min() -> str:
    return _compiled(
        sf.Fusion(_MEMBERS, signals={"ent": sf.Entropy()}, synthesizer=_pick("ent", "min"))
    )


def logprob_entropy_shared() -> str:
    return _compiled(
        sf.Fusion(
            _MEMBERS,
            signals={"lp": sf.Logprob("mean"), "ent": sf.Entropy()},
            synthesizer=_pick("lp"),
        )
    )


BUILDERS: dict[str, Callable[[], str]] = {
    "logprob_pick_mean_candidate.url4": logprob_pick_mean,
    "logprob_vote_prob_candidate.url4": logprob_vote_prob,
    "logprob_filter_mean_candidate.url4": logprob_filter_mean,
    "logprob_steer_filter_candidate.url4": logprob_steer_filter,
    "logprob_samples_pick_candidate.url4": logprob_samples_pick,
    "logprob_rank_mean_candidate.url4": logprob_rank_mean,
    "logprob_pick_sum_candidate.url4": logprob_pick_sum,
    "logprob_filter_prob_candidate.url4": logprob_filter_prob,
    "entropy_pick_min_candidate.url4": entropy_pick_min,
    "logprob_entropy_shared_candidate.url4": logprob_entropy_shared,
}


def write_fixture(name: str) -> None:
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_logprob_entropy_fixture_matches_the_sdk_compile(name: str) -> None:
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture()"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
