"""Retired at OME-1209 Stage E4a: how a proven row-11 shadow mutation wrote.

These tests pinned the shadow mutation's writes: the publication and the Profile blob's retirement
in one transaction, eviction of both owners' cached credentials after the commit, and supersession
by an identity change after the proof. E4a removes the shadow proof with the Profile document's
part in the pair table (spec §9 Q8), so a pair has one owner and a mutation retires no Profile blob.

Successors:
- PUT eviction after its own commit: `test_connection_backed_admin.py::`
  `test_set_api_key_writes_the_effective_connection_and_mirrors_the_document`;
- DELETE eviction: `test_connection_backed_admin_delete_list.py::`
  `test_delete_revokes_the_effective_connection_and_clears_the_reference`;
- the remaining post-capture fence: `test_pair_admin_mutations.py::`
  `test_a_live_row_added_after_the_capture_supersedes_the_publication`.
"""
