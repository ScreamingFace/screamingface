"""Retired at OME-1209 Stage E3: the Profile writers' refusal of saved defaults (OME-1323, D2).

This module pinned that the tenant/admin Profile API-key PUT, the Profile OAuth start and the
tenant/admin Profile PATCH refused a present `defaults` member with `defaults_not_accepted`
before any side effect. Since Stage E3 each of those writers answers 410
`legacy_profile_api_retired` before body parsing, so a `defaults` member can no longer reach
them and every test here retired with its route.

Successor coverage:
- the 410 answer, which a body does not change: `test_legacy_profile_routes_retired.py`;
- the D18 admin PUT refusal: `test_admin_connections_mutation_routes.py`
  (`test_saved_defaults_keep_their_existing_refusal`);
- the native tenant writers' handling of `defaults`:
  `test_profile_retirement_successor_coverage.py`.
"""
