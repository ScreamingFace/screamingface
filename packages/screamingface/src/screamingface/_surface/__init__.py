"""The map → select → reduce recipe surface (E4b, OME-1653), private until the swap.

FEATURE: one grammar, composed left to right with ``>>``::

    Fanout(members, signals=...)  >>  [Judge]  >>  [Rank | Filter]*  >>  terminal

A ``Fanout`` opens a block, and a reducer (``Vote``, ``Median``, ``Mean``) or a writer
(``Synthesize``) closes it. ``lowering.lower`` turns a chain into today's values, so it compiles to
the url4 of today.
INVARIANT: this package is not exported from ``screamingface``: only new tests import it until the
swap (unit 7) makes these names ``sf.*``. Units 3–6 add the judge, narrow and gate steps.
"""

from screamingface._surface.chain import Pipeline
from screamingface._surface.fanout import Fanout
from screamingface._surface.refs import Extract, signal
from screamingface._surface.steps import Mean, Median, Vote
from screamingface._surface.synthesize import Synthesize

__all__ = [
    "Extract",
    "Fanout",
    "Mean",
    "Median",
    "Pipeline",
    "Synthesize",
    "Vote",
    "signal",
]
