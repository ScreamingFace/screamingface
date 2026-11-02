"""Retired at OME-1209 Stage E3: pending-OAuth cancellation ordering in the Profile API-key PUT.

This module (OME-307 Unit 5) pinned that the tenant Profile API-key PUT did not cancel a pending
OAuth flow until its publication committed, under both a failed and a cancelled publication.
Since Stage E3 that route answers 410 `legacy_profile_api_retired` before any I/O, so the writer
whose ordering was under test no longer runs in production and both tests retired with it.

Successor coverage:
- the 410 answer: `test_legacy_profile_routes_retired.py`;
- atomic, cancellation-safe native API-key publication: `test_api_key_connection_races.py`
  (`test_create_connection_cancelled_after_blob_write_commits_neither_row_nor_blob`) and
  `test_oauth_connection_api_key_routes.py` (`test_create_api_key_atomic_on_persist_failure`);
- the D18 admin write dropping only the pair's pending flows after commit:
  `test_admin_connections_mutation_routes.py`
  (`test_a_committed_mutation_drops_only_the_pairs_pending_flows`).
"""
