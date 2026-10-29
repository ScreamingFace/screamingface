"""Retired at OME-1138 Stage E, E5c: a pre-E3b Profile index payload stayed readable.

This module pinned that a legacy OAuth generation map in an index row was ignored and dropped on
the next mutation. The index store and every index row are gone (E5b purge, E5c deletion), so no
payload of any shape is read any more.

Successor coverage: the store is absent and no module imports it —
`test_profile_index_offline_only.py`.
"""
