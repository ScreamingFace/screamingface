"""OME-638: which request paths a profile default actually WROTE — retired at Stage E, E2b.

# WHY empty: these were pure unit tests over `_apply_defaults`, the saved-defaults merge. Stage C
# (OME-1323) stopped chat from merging stored Profile defaults, and E2b (OME-1209) deleted the
# merge itself, so there is no function left to pin. That chat ignores stored defaults stays
# proven by `test_chat_saved_defaults_are_not_merged`.
"""
