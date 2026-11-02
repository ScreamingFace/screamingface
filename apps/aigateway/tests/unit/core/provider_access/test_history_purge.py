"""Retired at OME-1138 Stage E, E5c: the history purge on SQLite (E5b, spec C1-C5).

This module pinned what the purge deleted (index rows, unaddressed provider blobs), what it kept
(every blob a Connection row addresses, the JWT secret, rows outside a provider namespace) and
when it skipped an account. The purge ran in dev, stage and prod on 2026-10-28, and E5c deleted
`core/provider_access/history_purge.py` and `history_references.py` with the command (spec Q5).

Successor coverage: the modules and the command are absent — `test_profile_index_offline_only.py`.
"""
