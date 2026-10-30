"""The Run registry: the Engine App's record of every evaluation (OME-1785, E5 P1).

FEATURE: first-class Runs — an id, an owner, per-Candidate outcomes, a derived state and a
retention period, so a researcher can list and reopen Runs from any notebook.

INVARIANT (spec §9): this package is control plane only. The runner, the worker and every shared
leaf never import it, and only it may import a database driver; `.claude/scripts/check_layering.py`
enforces both.
"""
