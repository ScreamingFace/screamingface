"""Retired at OME-1209 Stage E3b: the Profile-backed `ProviderCredentialAdmin` (ops 7-9).

This module pinned the Profile-backed admin interface behind the tenant Profile routes: masked
listings with their legacy projection, the API-key write (index row first, blob second, one
transaction, delete-wins) and the named delete. Stage E3 answered those routes with a static 410,
and Stage E3b deleted the interface, its wiring and both backings' ops 7-9, so the tests retired
with them.

Successor coverage (the D18 admin PUT and DELETE, `pair_admin_writes`):
- a key on an empty or sole-Profile pair: `test_pair_admin_mutations.py`
  (`test_put_on_an_empty_pair_creates_one_connection_at_the_default_address`,
  `test_put_beside_a_sole_profile_mints_at_the_default_address_and_leaves_it`);
- a provider without API keys (write order and index conflicts retired at E4b):
  `test_pair_admin_publication.py`, `test_admin_connections_mutation_routes.py`;
- races with a concurrent delete or live row: `test_pair_admin_mutations.py`
  (`test_a_live_row_added_after_the_capture_supersedes_the_publication`,
  `test_a_live_row_added_after_a_delete_captured_the_pair_supersedes_it`);
- a store outage and its rollback: `test_pair_admin_mutations.py`
  (`test_a_store_outage_inside_the_write_is_the_scoped_write_refusal`) and
  `test_connection_backed_admin.py`
  (`test_a_failing_credential_store_rolls_back_the_connection_and_the_marker`);
- cache eviction: `test_pair_admin_mutations.py`
  (`test_the_mutation_evicts_the_cached_credential_it_changed`);
- an unknown provider: `test_pair_admin_mutations.py`
  (`test_an_unknown_provider_keeps_the_existing_refusal`);
- the delete: `test_pair_admin_mutations.py`
  (`test_delete_ends_a_sole_profile_without_a_dummy_connection`,
  `test_delete_on_an_empty_pair_is_a_no_op_that_mints_no_marker`);
- masked listings: `test_pair_admin_disposition.py`
  (`test_a_profile_only_pair_lists_its_legacy_owner`,
  `test_a_migrated_pair_lists_its_effective_connection`,
  `test_the_inventory_writes_nothing_and_reads_no_credential`).
"""
