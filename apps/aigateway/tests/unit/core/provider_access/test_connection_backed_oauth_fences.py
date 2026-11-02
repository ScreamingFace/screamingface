"""Retired at OME-1209 Stage E3b: fences and failures of the migrated pair's legacy OAuth flow.

This module pinned the legacy Profile OAuth flow of a migrated pair: an overtaken generation, a
delete or an API key between start and callback, failed exchanges, a store outage, a revoked row
and an identity held elsewhere. The flow's only start answers 410 since Stage E3, and Stage E3b
deleted the facade and the callback branches it fed, so these tests retired with them.

Successor coverage (the native flow's repair callback):
- an overtaken flow or a moved marker: `test_native_oauth_replaces_unusable_effective.py`
  (`test_a_marker_move_between_start_and_callback_wins`,
  `test_the_first_of_two_repairs_wins_and_the_second_publishes_nothing`);
- a delete or a revoke between start and callback:
  `test_native_oauth_replaces_unusable_effective.py`
  (`test_a_delete_between_start_and_callback_wins`);
- an API key written in between: `test_native_api_key_replaces_effective.py`
  (`test_a_marker_move_during_the_validation_wins_and_creates_nothing`);
- failed exchanges: `tests/unit/test_oauth_connections_routes.py`
  (`test_failed_anthropic_connection_can_retry_same_label`,
  `test_token_endpoint_returns_401_and_marks_error_when_refresh_token_revoked`) and
  `test_native_oauth_replaces_unusable_effective.py`
  (`test_a_usable_effective_row_is_not_displaced`,
  `test_an_effective_row_that_breaks_after_the_start_is_not_replaced`);
- a store outage and an identity conflict: `test_native_oauth_replaces_unusable_effective.py`
  (`test_a_credential_store_outage_publishes_nothing`,
  `test_an_activation_conflict_publishes_nothing`);
- a failure whose pending row was taken: `test_writer_floor_native.py`
  (`test_a_native_callback_publication_failure_does_not_claim_the_pair`);
- the manual code exchange: `tests/unit/test_auth_routes.py`
  (`test_connection_exchange_uses_redirect_uri_override`).
"""
