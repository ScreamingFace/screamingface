"""Retired at OME-1138 Stage E, E5c: the purge against references it does not own (E5b).

This module pinned that a blob stayed when any Connection row of any account resolved to its whole
physical address. The purge has run in every environment, and E5c deleted it and
`core/provider_access/history_references.py`, which only the purge read (spec Q5).

Successor coverage: the purge and its reference reader are absent —
`test_profile_index_offline_only.py`.
"""
