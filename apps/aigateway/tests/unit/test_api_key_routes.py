"""Retired at OME-1138 Stage E, E5c: the Profile index's API-key-era shape (SF-244).

The last test here pinned that a legacy index row without `auth_type` read back as OAuth. The
index store and every index row are gone (E5b purge, E5c deletion). The tenant Profile API-key
routes had already retired at OME-1209 Stage E3 (`test_legacy_profile_routes_retired.py`).

Successor coverage: the native API-key Connection tests — `test_oauth_connection_api_key_routes.py`,
`test_api_key_connection_validation.py` and `test_api_key_connection_races.py`.
"""
