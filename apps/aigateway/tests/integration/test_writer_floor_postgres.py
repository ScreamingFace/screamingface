"""PostgreSQL races of the G0 writer floor on a legacy-owned pair (OME-1497) — retired.

# FEATURE: OME-1209 Stage E3 retired every test this module held. Each raced the Profile api-key
# route `PUT /v1/auth/{provider}/profiles/{name}/api-key` against a native writer or a second
# copy of itself. That route answers 410 before authentication, body or storage since E3, so no
# shipped writer can take the legacy side of these races any more; rebuilding it on a core op
# would prove nothing about shipped behaviour (owner decision D1).
# INVARIANT: the pair-claim fence these tests pinned is still covered by its successors:
# - `tests/integration/test_pair_admin_mutations_postgres.py` — two first-marker bridge writers and
#   a bridge put/delete on a sole Profile commit exactly one, with no orphan, on PostgreSQL;
# - `tests/integration/test_lifecycle_postgres_races.py` — native Connection delete/set commit
#   orders on PostgreSQL;
# - `tests/unit/core/provider_access/test_writer_floor_native.py` and
#   `test_writer_floor_native_compat.py` — native writers claim and keep the pair;
# - `tests/unit/test_api_key_connection_races.py` — native api-key create/replace/delete races.
"""
