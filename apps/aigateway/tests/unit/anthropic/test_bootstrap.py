"""Retired at OME-1209 Stage E4b: the opt-in Claude Code credential import at startup.

These tests pinned `bootstrap_from_claude_code`, which copied the local Claude Code credential into
a legacy Profile and its blob when `AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE=1`. E4b removes the import
with every other Profile writer (plan §3 E4b), so no runtime path writes a Profile document.

Successors, both in `tests/unit/test_profile_index_offline_only.py`:
- the import, its settings and its error are gone:
  `test_the_profile_writers_and_the_startup_import_are_gone`;
- no module reads the flag (its warning retired in the OME-1138 close-out, L4a):
  `test_no_module_reads_the_retired_bootstrap_flag`.
"""
