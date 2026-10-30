"""Retired at OME-1209 Stage E4b: the G0 writer floor of the opt-in startup import.

These tests pinned `bootstrap_under_the_floor`: the startup import claimed a `none` or
`quarantined` pair, skipped a `migrated` one, and left the marker untouched when it imported
nothing. E4b removes the import (plan §3 E4b), so no startup path writes a Profile or claims a
pair.

Successors:
- `tests/unit/test_profile_index_offline_only.py::`
  `test_a_set_bootstrap_flag_only_warns_that_the_import_is_retired` (the marker stays `none` at
  generation 0);
- the Connection-side fences that remain: `test_writer_floor_native.py`.
"""
