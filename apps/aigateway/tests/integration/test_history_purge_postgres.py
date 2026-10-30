"""Retired at OME-1138 Stage E, E5c: the history purge's fence on PostgreSQL (E5b, C3/C4).

This module pinned that a reference created while the purge held an account waited and kept its
key, and that a purge coming second kept the referenced blob. The purge has run in every
environment and E5c deleted it (spec Q5).

Successor coverage: the purge is absent — `tests/unit/test_profile_index_offline_only.py`.
"""
