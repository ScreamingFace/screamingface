"""Retired at OME-1209 Stage E4b: the index-before-credential lock order of OAuth completion.

The test pinned that OAuth completion wrote the account's Profile index row before the optional
credential row, the order index-first writers needed on PostgreSQL. E4b removes the index write
from completion, so every writer now takes marker → Connection row → blob.

Successors:
- no index write on completion: since OME-1138 Stage E, E5c the index no longer exists
  (`test_profile_index_offline_only.py`);
- the one lock order on PostgreSQL:
  `tests/integration/test_provider_access_shared_addresses_postgres.py`.
"""
