"""Retired at OME-1138 Stage E, E5c: the backfill's write half (OME-1208, S4).

This module pinned apply, dry-run and the R1 rollback of `migrate_profiles`: a Profile-only pair
migrated onto its own blob address, idempotence, crash and race safety, and leak-free reports. The
backfill ran before E5b's purge removed the Profile storage, and E5c deleted
`core/provider_access/backfill_apply.py` with the command.

Successor coverage:
- the module and the command are absent: `test_profile_index_offline_only.py`;
- the migrated pair the backfill produced, as the runtime serves it:
  `test_connection_only_resolve.py`, `test_connection_backed_native_routes.py`.
"""
