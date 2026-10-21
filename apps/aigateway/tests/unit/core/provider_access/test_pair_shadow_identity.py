"""Retired at OME-1209 Stage E4a: row 11, the legacy OAuth shadow proven by identity.

These tests pinned the D18 identity proof: a `none` pair holding a Profile document plus a shadow
Connection at a different (UUID) locator was managed only when both OAuth identities matched.
E4a removes the Profile document from the pair table (spec §9 Q8): such a pair is now the
single-Connection row (9), adopted without a proof, and no mutation decrypts a credential to
compare identities.

Successors (`test_pair_admin_connection_only.py` unless named otherwise):
- adoption of the one Connection beside a Profile:
  `test_put_adopts_the_one_connection_of_a_none_pair_beside_a_profile`;
- LIST of that pair: `test_list_shows_the_one_connection_beside_several_profiles`;
- DELETE retires the Connection only: `test_delete_leaves_a_profile_only_pair_untouched` and
  `test_pair_admin_mutations.py::test_delete_revokes_a_sole_connection_and_its_blob`;
- row 11 is refused with no identity read: `test_row_11_is_refused_without_an_identity_proof`
  and `test_pair_admin_mutations.py::test_an_unmanageable_pair_refuses_and_writes_nothing`
  (`migrated-null-live`).
"""
