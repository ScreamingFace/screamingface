"""Retired at OME-1209 Stage E3b: the Profile-era OAuth flow seeder.

`open_oauth_flow` reproduced the storage effects of the retired Profile OAuth start so tests could
reach the callbacks' legacy-pending and migrated-facade branches. Both branches retired at E3b:
every pending flow is now a native Connection flow, opened by `POST /v1/oauth/connections`.

Successors:
- callback tests open their flow natively: `test_auth_routes.py` (`_open_flow`, which also seeds
  a PENDING compat document for the D14 mirror, and `_seed_pending_flow`);
- the cancellation re-put: `test_profile_oauth_flow_ownership.py`;
- the native lock order: `test_profile_publication_locking.py`.
"""
