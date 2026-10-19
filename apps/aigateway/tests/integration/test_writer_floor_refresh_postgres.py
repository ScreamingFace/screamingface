"""PostgreSQL races of the G0 refresh guard on an unmarked legacy pair (OME-1497) — retired.

# FEATURE: OME-1209 Stage E3 retired every test this module held. Each raced the manual Profile
# refresh `POST /v1/auth/{provider}/profiles/{name}/refresh` against the Profile api-key route or
# the Profile delete route. All three answer 410 before authentication, body or storage since E3,
# so neither side of these races is a shipped writer any more; rebuilding them on core ops would
# prove nothing about shipped behaviour (owner decision D1).
# INVARIANT: the refresh-guard ordering these tests pinned is still covered by the dispatch and
# native twins in `tests/unit/core/provider_access/test_writer_floor_refresh.py`:
# - `test_a_dispatch_refresh_on_a_migrated_pair_deleted_in_its_window_resurrects_nothing`;
# - `test_a_reauth_in_flight_survives_an_ordinary_refresh`;
# - `test_a_dispatch_refresh_of_a_marked_pair_loses_to_a_key_replacement`;
# - `test_a_key_replacement_right_after_a_refresh_publication_is_not_reverted`;
# - `test_a_dispatch_refresh_stamps_the_profile_in_its_publication`;
# and by the native writer floor in `test_writer_floor_native.py` and
# `tests/unit/test_api_key_connection_races.py`.
"""
