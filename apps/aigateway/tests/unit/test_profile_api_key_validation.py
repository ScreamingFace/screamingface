"""Retired at OME-1209 Stage E3: Profile API-key validation before every side effect.

This module pinned that a rejected key on the tenant Profile API-key PUT touched no pending OAuth
state, no index row, no credential blob and no provider session. Since Stage E3 that route
answers 410 `legacy_profile_api_retired` before any I/O, so the test retired with it.

Successor coverage:
- the 410 answer: `test_legacy_profile_routes_retired.py`;
- native validation before persistence: `test_api_key_connection_validation.py`
  (`test_create_validation_failure_precedes_blob_and_cache_mutation`,
  `test_create_maps_every_non_valid_state_without_persistence`);
- the D18 admin write: `test_admin_connections_mutation_routes.py`
  (`test_a_rejected_key_keeps_the_existing_refusal_and_writes_nothing`).
"""
