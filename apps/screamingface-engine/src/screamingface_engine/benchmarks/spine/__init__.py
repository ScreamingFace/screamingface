"""The benchmark spine — grading machinery shared by every board (OME-1024).

Modules here are extracted one ticket at a time from the per-board aggregate files.
AIDEV-NOTE: never edit `benchmarks/aggregation.py` or `benchmarks/contract.py` from a
spine extraction — the live-progress branches (OME-932, OME-934) own those files; the
spine grows beside them as new modules only.
"""

from screamingface_engine.benchmarks.spine.case_ladder import CaseLadder

__all__ = ["CaseLadder"]
