"""sf.Vote and sf.Median are the named forms of sf.Reduce rows (OME-1289 gap, BK#1-4).

FEATURE: a named reducer and its block form compile to the same combine call.
INVARIANT: both build a ``_ReducerPlan`` (the seam), so their url4 bytes are equal by construction.
"""

from __future__ import annotations

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
