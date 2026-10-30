"""Retired at OME-1138 Stage E, E5c: no runtime path wrote a Profile document (E4b, spec Q10).

This module pinned that the native OAuth callback, the native key replacement and delete, and the
D18 PUT and DELETE left a seeded Profile document as it was, through a spy on every
`ProfileIndexStore` write. E5c deleted the store and the model, so no path can write a document.

Successor coverage:
- nothing imports the index or its models: `test_profile_index_offline_only.py`;
- a blob goes with its last live Connection (D5, D11):
  `test_pair_admin_mutations.py` (`test_delete_on_a_same_locator_pair_retires_the_row_and_the_blob`)
  and `test_connection_backed_native_routes.py`
  (`test_deleting_the_effective_row_retires_the_pair`).
"""
