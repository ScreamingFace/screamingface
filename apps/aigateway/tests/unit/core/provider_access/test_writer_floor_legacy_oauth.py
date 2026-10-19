"""Retired at OME-1209 Stage E3b: the G0 writer floor of the legacy Profile OAuth callback.

This module pinned that a legacy Profile OAuth callback claimed the pair it observed at start,
lost to a later ownership change and wrote its shadow Connection only at the published
generation. The legacy start answers 410 since Stage E3, and Stage E3b deleted the callback
branch, so these tests retired with it.

Successor coverage (the native callback claims the same way):
- the claim at the callback: `test_writer_floor_native.py`
  (`test_a_native_oauth_start_and_its_callback_each_claim_and_keep_the_pair_legacy_owned`);
- a callback after another ownership change: `test_writer_floor_native.py`
  (`test_a_native_callback_after_another_ownership_change_loses_and_activates_nothing`,
  `test_a_native_callback_that_lost_the_pair_before_activation_activates_nothing`);
- a quarantined pair keeps its state and note: `test_writer_floor.py`
  (`test_a_claim_keeps_a_quarantined_state_and_its_note`).
"""
