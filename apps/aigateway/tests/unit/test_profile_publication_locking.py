"""Retired at OME-1209 Stage E4b: the index-before-credential lock order of OAuth completion.

The test pinned that OAuth completion wrote the account's Profile index row before the optional
credential row, the order index-first writers needed on PostgreSQL. E4b removes the index write
from completion, so every writer now takes marker → Connection row → blob.

Successors:
- no index write on completion: `core/provider_access/test_no_profile_writer.py::`
  `test_a_native_callback_leaves_a_same_named_document_as_it_was`;
- the one lock order on PostgreSQL:
  `tests/integration/test_provider_access_shared_addresses_postgres.py`.
"""
