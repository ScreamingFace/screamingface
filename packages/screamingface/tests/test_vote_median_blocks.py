"""sf.Vote and sf.Median are the named forms of sf.Reduce rows (OME-1289 gap, BK#1-4).

FEATURE: a named reducer and its block form compile to the same combine call.
INVARIANT: both build a ``_ReducerPlan`` (the seam), so their url4 bytes are equal by construction.
"""

from __future__ import annotations

import pytest
from _reducer_fixtures import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer

_MEMBERS = ["provider/a", "provider/b", "provider/c"]


def _url4(synthesizer: Reducer) -> str:
    recipe = sf.Fusion(_MEMBERS, synthesizer=synthesizer)
    return compile_candidate(recipe, operators=engine_operators()).url4


def test_named_reducers_build_a_reducer_plan() -> None:
    # BK#2: Vote and Median go through the plan seam, not a private steps API of their own.
    for cls in (sf.Vote, sf.Median):
        for gone in ("_steps", "_reducer", "_kind"):
            assert not hasattr(cls, gone), f"{cls.__name__}.{gone} is replaced by _plan()"
    vote = sf.Vote(extract="last_number", normalize="numeric")
    vote_block = sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric"))
    assert vote._plan() == vote_block._plan()
    assert sf.Median()._plan() == sf.Reduce("median", extract=sf.Extract("last_number"))._plan()
    compute = sf.Reduce("median", mode="compute", extract=sf.Extract("last_number"))
    assert sf.Median(select="value")._plan() == compute._plan()
    assert sf.Vote(normalize=None)._plan().steps.normalize is None


def test_reduce_plurality_compiles_byte_identical_to_vote() -> None:
    # BK#3: guard. The seam makes the pair equal by construction, so this passes at once.
    vote = sf.Vote(extract="last_number", normalize="numeric")
    block = sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric"))

    assert _url4(vote) == _url4(block)


_VOTE_RULES = ("boxed", "last_number", "last_line", "whole", "inspect_number", "inspect_aime")
_VOTE_NORMALIZERS = (None, "numeric", "text", "set", "inspect_numeric", "identity")
_MEDIAN_RULES = ("last_number", "boxed", "last_line", "whole", "inspect_number", "inspect_aime")


@pytest.mark.parametrize("normalize", _VOTE_NORMALIZERS)
@pytest.mark.parametrize("rule", _VOTE_RULES)
def test_every_plurality_row_matches_vote(rule: str, normalize: str | None) -> None:
    # BK#4. json, field and regex have no arg-less Vote form; json_object@1 arrives in 9E.
    vote = sf.Vote(extract=rule, normalize=normalize)
    block = sf.Reduce("plurality", extract=sf.Extract(rule, normalize=normalize))  # type: ignore[arg-type]

    assert _url4(vote) == _url4(block)


@pytest.mark.parametrize(("select", "mode"), [("nearest", None), ("value", "compute")])
@pytest.mark.parametrize("rule", _MEDIAN_RULES)
def test_every_median_row_matches_median(rule: str, select: str, mode: str | None) -> None:
    median = sf.Median(extract=rule, select=select)
    block = sf.Reduce("median", mode=mode, extract=sf.Extract(rule))  # type: ignore[arg-type]

    assert _url4(median) == _url4(block)
