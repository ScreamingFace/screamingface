"""The Run registry's tables (OME-1785, E5 P1 spec §4.3): facts only, never a Run's state.

One file per model, each with its abstract `Base*` (the tortoise-dev house rules). Only
`runs/store.py` reads or writes them; the rest of the App speaks `runs.records`.
"""

from screamingface_engine.runs.models.candidate import BaseCandidate, Candidate
from screamingface_engine.runs.models.run import BaseRun, Run

__all__ = ["BaseCandidate", "BaseRun", "Candidate", "Run"]
