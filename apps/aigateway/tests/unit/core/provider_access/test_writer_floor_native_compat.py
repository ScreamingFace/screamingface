"""Retired at OME-1209 Stage E4b: a compat-document conflict on the native OAuth callback.

The test pinned that a Profile-index write that ran out of retries inside the callback's activation
rolled the activation back and answered 503 `profile_index_conflict`. E4b removes the D14 mirror,
so the callback writes no Profile document and no index conflict can surface on it.

Successors:
- `test_no_profile_writer.py::test_a_native_callback_leaves_a_same_named_document_as_it_was`;
- a failed publication still rolls the callback back: `test_writer_floor_native.py::`
  `test_a_native_callback_publication_failure_leaves_same_named_profile_unchanged`.
"""
