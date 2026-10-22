"""Retired at OME-1209 Stage E4a: the Profile owner presence fence of a dispatch refresh.

`test_a_refresh_loses_to_a_document_removal_that_moves_no_marker` pinned that a refresh of a
Profile credential published only while its document still owned the credential, even when nothing
moved the marker. Resolve reads no Profile document since E4a, so no refresh targets one, and the
Profile refresh owner that held this fence is gone; a refresh's owner is always a Connection.

Successors in `test_writer_floor_refresh.py` (the Connection owner presence fence, no marker move):
- `test_a_native_refresh_whose_row_was_revoked_in_its_window_writes_nothing`;
- `test_a_token_refresh_of_a_revoked_non_effective_row_on_a_migrated_pair_writes_nothing`.
"""
