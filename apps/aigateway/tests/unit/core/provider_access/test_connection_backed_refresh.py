"""Retired at OME-1209 Stage E3: the Profile refresh facade of a migrated pair.

# WHY no tests remain: every test here drove `POST /v1/auth/{provider}/profiles/{name}/refresh`,
# which answers 410 `legacy_profile_api_retired` since Stage E3 — the route itself was the subject,
# so its tests retired with it.
# INVARIANT (still covered by successors): refreshing a migrated pair's effective Connection
# rewrites the locator blob, marks only the row on rejection, and never refreshes an errored row —
# `test_connection_backed_native_routes.py` (`POST /v1/oauth/connections/{id}/refresh` and the
# token path) and the dispatch-refresh tests in `test_writer_floor_refresh.py`.
"""
