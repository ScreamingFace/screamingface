"""Retired at OME-1209 Stage E3: the Profile API-key PUT racing an older in-flight OAuth callback.

This module pinned that a Profile API-key PUT committed during an older flow's token exchange won
over the callback (`profile_auth_conflict`). Its only legacy actor is the tenant Profile API-key
PUT, which answers 410 `legacy_profile_api_retired` since Stage E3, so the race no longer exists in
production (owner decision D1: retire) and the test retired with it.

Successor coverage:
- the 410 answer: `test_legacy_profile_routes_retired.py`;
- native API-key races: `test_api_key_connection_races.py`;
- a stale callback never overwriting a newer owner: `test_profile_oauth_flow_ownership.py`.
"""
