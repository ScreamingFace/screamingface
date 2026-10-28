"""Retired at OME-1138 Stage E, E5c: the backfill's read-only classification (OME-1208, S4).

This module pinned how every pair was classified from the legacy index, its Connections and its
marker before the backfill changed an owner. The index is gone, and E5c deleted
`core/provider_access/backfill_classify.py` with the command.

Successor coverage: the module is absent and nothing imports the index —
`test_profile_index_offline_only.py`.
"""
