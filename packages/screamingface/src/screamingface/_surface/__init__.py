"""The map → select → reduce recipe surface (E4b, OME-1653), private until the swap.

FEATURE: one grammar, composed left to right with ``>>``::

    Fanout(members, signals=...)  >>  [Judge]  >>  [Rank | Filter]*  >>  terminal

A ``Fanout`` opens a block, a ``Judge`` scores it, the narrow steps (``Rank``, ``Filter``,
``Concat``) make the panel smaller, and a reducer (``Vote``, ``Median``, ``Mean``, ``ArgMax``,
``ArgMin``, ``First``, ``Merge``, ``JudgePick``, ``Gate``) or a writer (``Synthesize``) closes it.
``lowering.lower`` turns a chain into today's values, so it compiles to the url4 of today.
INVARIANT: this package is not exported from ``screamingface``: only new tests import it until the
swap (unit 7) makes these names ``sf.*``.
"""

from screamingface._surface.chain import Pipeline
from screamingface._surface.fanout import Fanout
from screamingface._surface.gate import Gate
from screamingface._surface.judge import Judge, JudgePick
from screamingface._surface.refs import Extract, agreement, field, signal
from screamingface._surface.steps import (
    ArgMax,
    ArgMin,
    Concat,
    Filter,
    First,
    Mean,
    Median,
    Merge,
    Rank,
    Vote,
)
from screamingface._surface.synthesize import Synthesize
from screamingface.blocks import matches
from screamingface.fields import FieldRule

__all__ = [
    "ArgMax",
    "ArgMin",
    "Concat",
    "Extract",
    "Fanout",
    "FieldRule",
    "Filter",
    "First",
    "Gate",
    "Judge",
    "JudgePick",
    "Mean",
    "Median",
    "Merge",
    "Pipeline",
    "Rank",
    "Synthesize",
    "Vote",
    "agreement",
    "field",
    "matches",
    "signal",
]
