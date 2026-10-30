"""Retired at OME-1138 Stage E, E5c: the anonymous account in the purge's `--all` (E5b).

This module pinned that the purge reported an unmaterialised anonymous account as skipped and
swept nothing of it. The purge has run in every environment and E5c deleted it (spec Q5).

Successor coverage: the purge is absent — `test_profile_index_offline_only.py`.
"""
