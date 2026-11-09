"""Retired at OME-1209 Stage E3: the Profile management routes as shells over the boundary.

This module pinned that the tenant and admin Profile PUT/DELETE/listing routes (OME-1230, Stage
A3) validated, called `ProviderCredentialAdmin`, rendered its refusals and returned its
projection. Since Stage E3 every one of those routes answers 410 `legacy_profile_api_retired`
before authentication, body parsing or storage, so no shell is left to observe and every test
here retired with its route.

Successor coverage:
- the 410 answer and its successor pointer: `test_legacy_profile_routes_retired.py`;
- the tenant API-key surface: `test_oauth_connection_api_key_routes.py`,
  `test_api_key_connection_validation.py` and `test_api_key_connection_races.py`;
- the admin surface: `test_admin_connections_mutation_routes.py` and
  `test_admin_connections_list_route.py`;
- admin-to-tenant scoping and blob removal: `test_profile_retirement_successor_coverage.py`.
"""
