"""Retired at OME-1138 Stage E, E5c: `python -m aigateway.migrate_profiles`.

This module pinned the backfill's command line (OME-1208, S4): modes, scope, exit codes, the JSON
report, the journal and the `-m` entry point. The backfill migrated the Profile-only pairs before
E5b's purge removed the Profile storage, and E5c deleted the command with the backfill modules.

Successor coverage:
- the command no longer imports: `test_profile_index_offline_only.py`;
- pair authority from Connections alone: `core/provider_access/test_connection_only_resolve.py`
  and `core/provider_access/test_pair_admin_mutations.py`.
"""
