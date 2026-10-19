"""Retired at OME-1209 Stage E3b: the Profile-facade OAuth flow of a migrated pair (S2'b2).

This module drove the legacy Profile OAuth flow over a migrated pair: the callback republishing
the effective Connection in place, a pending Connection for a pair without one, and the
unmigrated and quarantined pairs keeping the legacy flow. Its only producer, the Profile OAuth
start, answers 410 since Stage E3, and the pending table is per-process, so no such flow survives
a deploy. Stage E3b deleted the facade and the callback branches, and these tests retired with
them.

Successor coverage (the native start `POST /v1/oauth/connections` and its callback):
- in-place republication and a same-identity re-login:
  `test_native_oauth_replaces_unusable_effective.py`
  (`test_a_flow_named_like_the_effective_row_replaces_it_even_when_it_works`,
  `test_a_same_label_re_login_of_the_same_identity_replaces_the_effective_row`);
- a pair without a usable effective Connection:
  `test_native_oauth_replaces_unusable_effective.py`
  (`test_a_native_flow_replaces_an_unusable_effective_row`) and
  `tests/unit/test_oauth_connections_routes.py`;
- a re-login at the Connection's own locator: `test_native_unlabelled_targets_effective.py`
  (`test_an_unlabelled_re_login_of_the_same_identity_refreshes_the_main_connection`);
- unmigrated and quarantined pairs: `test_writer_floor_native.py`
  (`test_a_native_oauth_start_and_its_callback_each_claim_and_keep_the_pair_legacy_owned`) and
  `test_writer_floor.py` (`test_a_claim_keeps_a_quarantined_state_and_its_note`).
"""
