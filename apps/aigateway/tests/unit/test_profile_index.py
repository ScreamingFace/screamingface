"""Retired at OME-1138 Stage E, E5c: the Profile index store and its row types.

This module pinned `ProfileIndexStore` and the `Profile`/`ProfileIndex` models: the JSON round
trip, upsert/remove, the per-account rows seeded from the legacy global row, and the transition
conflicts. E5b's purge removed every index row from dev, stage and prod, and E5c deleted
`core/profile_index.py` and `core/profile_models.py`, so nothing is left to observe.

Successor coverage:
- the store and its models are absent and no module imports them:
  `test_profile_index_offline_only.py`;
- a stored credential is a Connection: `test_oauth_connection_api_key_routes.py`,
  `core/provider_access/test_connection_only_resolve.py`.
"""
