"""Retired at OME-1209 Stage E4b: a compat-document conflict on the native OAuth callback.

The test pinned that a Profile-index write that ran out of retries inside the callback's activation
rolled the activation back and answered 503 `profile_index_conflict`. E4b removes the D14 mirror,
so the callback writes no Profile document and no index conflict can surface on it.

Successors:
- no index write can happen: since OME-1138 Stage E, E5c the index no longer exists
  (`tests/unit/test_profile_index_offline_only.py`);
- a failed publication still rolls the callback back: `test_writer_floor_native.py::`
  `test_a_native_callback_publication_failure_leaves_same_named_profile_unchanged`.
"""
