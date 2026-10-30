"""Retired at OME-1138 Stage E, E5c: `python -m aigateway.purge_profile_history`.

This module pinned the purge's command line (E5b, spec C5): modes, scope, exit codes, the JSON
report, the journal and the `-m` entry point. The purge ran in dev, stage and prod on 2026-10-28,
and E5c retired the command with the Profile vocabulary (spec Q5).

Successor coverage: the command no longer imports — `test_profile_index_offline_only.py`.
"""
