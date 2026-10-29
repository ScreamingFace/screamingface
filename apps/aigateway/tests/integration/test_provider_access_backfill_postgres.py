"""Retired at OME-1138 Stage E, E5c: the backfill on PostgreSQL (OME-1208, S4).

This module pinned apply, the idempotent re-run and the first-marker race of `migrate_profiles` on
the production engine. The backfill ran before E5b's purge, and E5c deleted it with the command.

Successor coverage:
- the command is absent: `tests/unit/test_profile_index_offline_only.py`;
- the pair marker's compare-and-set on PostgreSQL: `test_provider_access_backing_postgres.py`.
"""
