"""Serial Candidate values: ``sf.Pipeline`` is the chain of the map → select → reduce surface.

WHY a module of its own: ``from screamingface.pipeline import Pipeline`` stays a valid import
(E4b surface D7-2: one ``Pipeline`` class, defined in ``screamingface._surface.chain``).
"""

from screamingface._surface.chain import Pipeline

__all__ = ["Pipeline"]
