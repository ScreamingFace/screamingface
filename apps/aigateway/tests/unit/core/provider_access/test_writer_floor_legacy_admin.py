"""Retired at OME-1209 Stage E4a: the D18 delete of a Profile-owned pair's blob.

The test pinned that `delete_pair` on a legacy-owned pair (row 8) removed the Profile blob unless
a LIVE Connection still addressed it. E4a removes row 8 (spec §9 Q8): a Profile beside a revoked
Connection is the empty pair, and DELETE on it writes nothing.

Successors:
- `test_pair_admin_connection_only.py::test_delete_leaves_a_profile_only_pair_untouched`;
- the shared-address guard: `test_pair_admin_publication.py::`
  `test_only_a_live_connection_at_the_profile_address_keeps_the_legacy_blob`.
"""
