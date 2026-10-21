# Owner list: unit 7 (the swap), test and data files changed in 9b4f3e84d..HEAD

Branch `OME-1653-e4b-display-gate-sums-consistency`, worktree `.claude/worktrees/e4b-consistency`.
Scope: every test or test-data file (`*/tests/**`) that existed at `e4d44281c` and that the range
`9b4f3e84d..HEAD` edited or deleted (`git diff --name-status`). Files are grouped by the step that
first changed them; "Also" names the later steps that changed the same file. The owner approves
this list; the main session writes `.claude/test-change-approvals/OME-1653.json` (not written here).

Not in the list (new in the range, so no approval of an existing pin): `tests/_nodes.py`,
`tests/data/surface_parity.json`, `tests/test_fusion_shortcut.py`, `tests/test_judge_template_v2.py`,
`tests/test_signal_key_paths.py`, `tests/test_surface_messages.py`, `tests/test_swap_prep.py`, and
`tests/test_migrate_surface.py` (added in 7c, deleted in 7f with `scripts/migrate_surface.py`).
Unit-1 files (approved 2026-10-20) are outside the range.

TOTAL 147 files: M=145, D=2

### 7b judge-template@2 pins (22 files)

- `apps/screamingface-engine/tests/unit/data/combine_contract/filter_judge_candidate.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/data/combine_contract/judge_order_min_candidate.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/data/combine_contract/judge_vote_candidate.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/data/combine_contract/quorum_judge_vote_candidate.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/data/combine_contract/recipe_s10.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/data/combine_contract/recipe_s11_max.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/test_sdk_candidate_contracts.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/test_sdk_filter_judge_contract.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/test_sdk_judge_order_contracts.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `apps/screamingface-engine/tests/unit/test_sdk_quorum_contracts.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `packages/screamingface/tests/data/fusion_docs/readme-345-by-scores.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `packages/screamingface/tests/data/fusion_docs/readme-387-judge-weighted.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `packages/screamingface/tests/data/fusion_docs/readme-397-judge-weighted-block.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `packages/screamingface/tests/data/fusion_docs/readme-514-ranked.url4` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `packages/screamingface/tests/test_filter_judge.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7d batches (groups 1-4); 7e codemod R13; 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7e review fixes.
- `packages/screamingface/tests/test_judge_link_trace.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_judge_order.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7d batches (groups 1-4); 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_judge_quorum.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7d batches (groups 1-4); 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_judge_reducer.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7d batches (groups 1-4); 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_judge_writer_warning.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7d batches (groups 1-4); 7d review fixes; 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_selection_input_bytes.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1).
- `packages/screamingface/tests/test_signal_recipe_fixtures.py` (edited): pins the judge-template@2 bytes or the @1 refusals (swap §1 7b, TM-1). Also: 7d-1 helpers and field picks.

### 7d-0 frozen parity and group D (10 files)

- `packages/screamingface/tests/_reducer_fixtures.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D). Also: 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_combine_evidence.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D).
- `packages/screamingface/tests/test_duplicate_members_warning.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D). Also: 7d batches (groups 1-4); 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_engine_url4_contract_fixtures.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D). Also: 7d batches (groups 1-4); 7e codemod R13.
- `packages/screamingface/tests/test_fixed_seed_sitting_warning.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D).
- `packages/screamingface/tests/test_reducer_fusion_quorum.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D). Also: 7d batches (groups 1-4); 7e codemod R13.
- `packages/screamingface/tests/test_reducer_slot.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D). Also: 7d batches (groups 1-4); 7e codemod R13; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_reducer_url4_round_trip.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D). Also: 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_samples_preflight.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D).
- `packages/screamingface/tests/test_url4_replay_fixed_seed_warning.py` (edited): reads surface_parity.json / tests/_nodes.py (D7-5), or builds FusionNode around a fixture reducer (D7-4, group D).

### 7d-1 helpers and field picks (22 files)

- `apps/screamingface-engine/tests/unit/data/combine_contract/recipe_s5.url4` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2).
- `apps/screamingface-engine/tests/unit/data/combine_contract/recipe_s5_pick_output.url4` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2).
- `apps/screamingface-engine/tests/unit/data/combine_contract/recipe_s7.url4` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2).
- `apps/screamingface-engine/tests/unit/test_combine_recipes.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2).
- `packages/screamingface/tests/_combine_flow_fixtures.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/_combine_recipes.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/_fusion_doc_examples.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/_signal_recipes.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/data/fusion_docs/readme-418-pick-confidence.url4` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2).
- `packages/screamingface/tests/data/fusion_docs/readme-528-rank-by-field.url4` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2).
- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/e2e/harness/fusion_golden.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7d review fixes; 7e codemod R13; 7f group F deletions.
- `packages/screamingface/tests/e2e/harness/goldens.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/e2e/harness/reducer_golden.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/e2e/test_fusion_golden_contracts.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions.
- `packages/screamingface/tests/e2e/test_reducer_golden_contracts.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/e2e/test_reducer_lane_contracts.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/e2e/test_report_tape.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/paid/_panel.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/paid/test_panel_models.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.
- `packages/screamingface/tests/test_fusion_recipe.py` (deleted): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7d batches (groups 1-4); 7e group F deletions.
- `packages/screamingface/tests/test_pick_output_url4_fixtures.py` (edited): codemod of the helpers to the sx surface, or the field-pick bytes that move (overview §4.2). Also: 7e codemod R13.

### 7d batches (groups 1-4) (84 files)

- `packages/screamingface/tests/e2e/test_local_provider_full_stack.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/paid/test_signal_sources_paid.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_accounting_evaluation.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_accounting_token_unknowns.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_band_api.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_benchmark_answer_rule.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_benchmark_compilation.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_benchmark_extract_evaluation.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_blocks_reduce.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7f src trim; 7g pinned messages and product gaps; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_check_surface_preflight.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_client_run.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_combine_sources.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_consistency_api.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_consistency_compile_guard.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_consistency_contract_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_consistency_display.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_consistency_member_labels.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_consistency_rebuild.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_consistency_sum_band.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_corrective_recipes.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_declared_signals.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_draco_vertical_slice.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_entropy_source.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_filter.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_filter_judge_url4_fixture.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_fusion_block_quorum.py` (deleted): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7f group F deletions.
- `packages/screamingface/tests/test_fusion_message.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_fusion_quorum.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_fusion_quorum_metadata.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_fusion_quorum_scope.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_fusion_retrieval_scope.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_gate_api.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_gate_contract_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_judge_blocks.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e group F deletions; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_judge_order_url4_contract_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_judge_url4_round_trip.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_judge_weighted_vote.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_judge_writer_warning_stages.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7f group F deletions.
- `packages/screamingface/tests/test_leaderboards.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_logprob_entropy_url4_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_logprob_source.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_mean.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7g pinned messages and product gaps; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_merge_writer_compile.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_model_parameter_preflight.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_paid_check_spend.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_panels_opt_out_of_maths.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_pick_by_signal.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_pick_merge_blocks.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_pick_merge_reducers.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_pick_merge_url4_round_trip.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions.
- `packages/screamingface/tests/test_pick_output.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_pipeline_compilation.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_pipeline_recipes.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_provider_access_preflight.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_quorum_url4_contract_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_rank_by_signal.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_rank_concat_reducers.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7f group F deletions.
- `packages/screamingface/tests/test_rank_concat_url4_round_trip.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e group F deletions; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7e review fixes.
- `packages/screamingface/tests/test_recipes.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_reduce_numeric_select.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7g pinned messages and product gaps; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_reducer_characterization.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_reducer_operator_catalog.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_reducer_recovery_preference.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_report_v1_vote_identity.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_rich_display.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_selection_compile_checks.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7g pinned messages and product gaps.
- `packages/screamingface/tests/test_shape_adaptive_linking.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_signal_sum_api.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7g pinned messages and product gaps; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_signal_vote_replay.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_signal_weighted_vote.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_sum_contract_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_unsupported_provider_parameter_preflight.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_url4.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_verbalized.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7e hand fixes, README-coupled, snapshot.
- `packages/screamingface/tests/test_verbalized_contract_fixture.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_vote_answers_trace.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_vote_median.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_vote_median_blocks.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_vote_median_contract_fixtures.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_weighted_median.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7d review fixes; 7e codemod R13; 7e hand fixes, README-coupled, snapshot; 7f group F deletions; 7g pinned messages and product gaps; 7h LO-P3 and the rg check.
- `packages/screamingface/tests/test_weighted_median_url4_fixture.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_weighted_vote.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e codemod R13.
- `packages/screamingface/tests/test_weighted_vote_contract_fixture.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f.
- `packages/screamingface/tests/unit/test_signal_key_conformance.py` (edited): codemod --to sx and its hand cases; rows of removed forms moved onto the internal nodes for 7f. Also: 7e hand fixes, README-coupled, snapshot.

### 7d review fixes (2 files)

- `packages/screamingface/tests/e2e/fixtures/fusion_lane.py` (edited): 7d review fixes (context block subjects as group F rows, warning/median/quorum/lowering/band rows). Also: 7f group F deletions.
- `packages/screamingface/tests/e2e/test_fusion_replay.py` (edited): 7d review fixes (context block subjects as group F rows, warning/median/quorum/lowering/band rows). Also: 7f group F deletions.

### 7e hand fixes, README-coupled, snapshot (4 files)

- `packages/screamingface/tests/public_surface_snapshot.json` (edited): 7e hand fixes (to_python strings, the one Pipeline D7-2, rebuild rows), README-coupled literals (D7-6), the public surface snapshot, or comments.
- `packages/screamingface/tests/test_consistency_docs.py` (edited): 7e hand fixes (to_python strings, the one Pipeline D7-2, rebuild rows), README-coupled literals (D7-6), the public surface snapshot, or comments.
- `packages/screamingface/tests/test_gate_docs.py` (edited): 7e hand fixes (to_python strings, the one Pipeline D7-2, rebuild rows), README-coupled literals (D7-6), the public surface snapshot, or comments.
- `packages/screamingface/tests/test_sum_band_docs.py` (edited): 7e hand fixes (to_python strings, the one Pipeline D7-2, rebuild rows), README-coupled literals (D7-6), the public surface snapshot, or comments.

### 7f group F deletions (1 files)

- `packages/screamingface/tests/e2e/test_fusion_lane_contracts.py` (edited): 7f group F: rows of code deleted by D7-8 (see the test ids below).

### 7g pinned messages and product gaps (2 files)

- `packages/screamingface/tests/test_blocks_extract.py` (edited): pins a 7g reworded message, or a product-gap row (a judge writer in a nested writer, the block named by its stage, field paths).
- `packages/screamingface/tests/test_pipeline_results.py` (edited): pins a 7g reworded message, or a product-gap row (a judge writer in a nested writer, the block named by its stage, field paths).

## Group F deletions by test id

### 7e (commit `8127d0848`, from the ledger)


  - `test_fusion_recipe.py` (whole file, 23 tests: `test_the_goldens_without_a_block_form_are_exactly_the_unnamed_pipeline_synthesizers`,
    `test_block_form_rewrites_to_fusion_and_compiles_byte_identical`, `test_rewrite_keeps_the_rest_of_the_pipeline`,
    `test_an_unnamed_pipeline_of_one_stage_is_that_stage_and_a_named_one_keeps_its_name`,
    `test_recipe_synthesizer_keeps_the_synthesis_flag_on_its_first_stage_only`, `test_named_pipeline_keeps_its_name_after_the_rewrite`,
    `test_nested_fusion_keeps_its_bindings_in_both_block_forms`, `test_every_recipe_without_a_context_block_is_returned_as_it_is`,
    `test_the_rewrite_is_idempotent`, `test_the_name_rule_infers_again_or_keeps_the_given_name`,
    `test_the_rewrite_reaches_loops_members_and_judges`, `test_the_rewrite_reaches_a_fusion_synthesizer_and_a_fusion_member`,
    `test_a_300_member_block_form_constructs_and_compiles_to_its_golden`, `test_only_the_context_block_skips_the_combine_exclusions`,
    `test_context_misuse_raises_before_spend`, `test_context_misuse_through_a_client_never_spends_or_fetches_operators`,
    `test_a_context_block_compiled_directly_is_the_misuse`, `test_the_synthesizer_operation_is_op_synthesis_n`,
    `test_recovered_fusion_prints_as_fusion`, `test_both_forms_report_the_same_candidate_name_in_a_scripted_run`,
    `test_a_cyclic_value_is_left_for_the_compiler_to_refuse`, `test_the_inferred_name_rule_lives_once_in_recipe_py`,
    `test_a_duplicate_name_made_by_the_rewrite_says_so_and_asks_for_a_name`): it read `Pipeline.stages`.
  - `test_blocks_reduce.py::test_equal_reduce_blocks_are_equal_and_hash_equal` (the `eval(_python())`
    loop over `_one_per_row()`); `test_reduce_to_python_round_trips` rows
    `Reduce('pick_field', field='score', order='min')`, `Reduce('top_k', k=2, by_field='score')`,
    `Reduce('top_k', k=2, by_field='a.b[0]', order='min')` (D7-8 forms: the rebuild refuses them).
  - `test_filter.py::test_reduce_filter_block_canonical_form_equality_and_hash` and
    `::test_filter_fields_repr_and_equality` (the `eval(_python())` loops).
  - `test_filter_judge.py::test_filter_block_and_repr_rebuild_the_judge_filter` (whole test).
  - `test_judge_blocks.py::test_judge_block_canonical_form_equality_and_hash` (the `eval` line).
  - `test_judge_order.py::test_public_surface_lists_judge_order` (JO#13: `Judge(returns=, order=)`).
  - `test_pick_merge_blocks.py::test_pick_and_merge_blocks_canonical_equality_hash_and_errors`
    (`_check_canonical_equality_and_hash`: the `eval(_python())` loop of 3 blocks).
  - `test_pick_output.py::test_url4_to_python_shows_the_output_of_each_pick` (the field order
    pair), `::test_block_forms_round_trip_to_the_named_pick_with_output` (the `pick_field` row),
    `::test_pick_field_block_python_round_trips` (whole test).
  - `test_rank_by_signal.py::test_rank_by_signal_fields_repr_and_equality` and
    `::test_reduce_top_k_block_canonical_form_equality_and_hash` (the `eval(_python())` loops).
  - `test_rank_concat_url4_round_trip.py::test_rank_and_concat_round_trip[rank by field]`,
    `::test_to_python_writes_the_reducers` (the by_field lines),
    `::test_the_recovered_reducers_equal_the_originals` (the 2 by_field shapes),
    `::test_a_followed_selection_inside_a_corrective_loop_round_trips` (the by_field solo loop).
  - Group F rows that still pass on the nodes stay for 7f (the by_field tamper rows of

### 7f (commit `555ba0002`; D7-8: the code these rows tested is deleted in `700c08beb`)

- test_blocks_reduce.py: the rows of the trimmed ops (argmax, top_k, filter, pick_field, concat, judge, merge, context) in
  test_reduce_without_required_option_raises_at_construction (7 rows), test_reduce_without_exactly_one_selector_raises_at_construction (whole),
  test_reduce_rejects_mode_the_op_does_not_have (compute ops + 4 select ops), test_reduce_rejects_unknown_op_and_foreign_options (context/top_k/judge/merge lines; judge check moves to weighted judge=),
  test_reduce_rejects_bad_option_values (15 rows), _one_per_row (10 rows; + mean row), test_equal_reduce_blocks_are_equal_and_hash_equal (pick_field True/1/1.0 rows),
  test_reduce_names_follow_the_spec_reducers (8 keys), test_reduce_repr_shows_mode_only_when_not_the_default (concat line),
  test_only_ops_with_engine_operators_compile_at_this_unit (context refusal + 5 op compile rows), test_reduce_to_python_round_trips (15 rows: judge x2, argmax x2, pick_field, merge x2, top_k x3, concat x2, filter x3); _OPS message lists 4 ops.
- test_lowering.py::test_lo0_lower_is_the_identity_on_todays_values[context-pipeline] (the context block node)
- test_fusion_block_quorum.py (whole file: test_the_block_form_with_quorum_compiles_to_the_named_form, test_a_rewritten_fusion_member_keeps_its_quorum, test_an_optional_block_form_member_stays_optional): the context block form.
- test_pick_merge_blocks.py: test_every_op_table_row_matches_its_named_form [order-max, equals-7-numeric, merge-model-field] and test_pick_and_merge_blocks_canonical_equality_hash_and_errors (the pick_field and merge blocks); test_field_rule_params_are_compared_by_type_and_value loses its ReduceNode('merge') and _FieldRules asserts (the public FieldRule/sf.Merge asserts stay).
- test_judge_writer_warning_stages.py::test_compile_names_the_users_stage_numbers[context-then-writer] and [context-then-judge] (the context rewrite)
- test_filter.py: test_reduce_filter_block_equals_sf_filter (whole), test_reduce_filter_block_canonical_form_equality_and_hash (whole); the ReduceNode('filter') lines of test_comparisons_compare_and_hash_by_a_typed_key (4 asserts), test_filter_benchmark_extract_resolves_from_the_benchmark_rule (the block equality), test_filter_validation (3 block refusals), test_filter_as_last_stage_is_rejected (the Reduce('filter') row -> the FilterNode node row); test_filter_fields_repr_and_equality (the _python line). Rows 2-3 (node as member / loop judge) KEPT: a hand-built url4 reaches the guard (product gap d).
- the old renderer's `_python()` asserts (D7-8, the old `to_python` renderers): test_band_api.py::test_a_gate_without_a_band_keeps_its_part_5_form, ::test_gate_takes_a_closed_band (1 each); test_consistency_api.py::test_consistency_holds_n_and_the_temperature (1); test_gate_api.py::test_vote_without_gate_keeps_its_bytes_repr_and_rebuild (1), ::test_gate_repr_and_python_form (4), ::test_vote_repr_and_rebuild_leave_verify_out (1); test_judge_weighted_vote.py::test_vote_repr_python_and_equality_carry_the_judge (1); test_signal_weighted_vote.py::test_signal_weights_value_repr_python_and_recovery (2); test_weighted_median.py::test_sdk_median_without_weights_compiles_the_same_bytes (1).
- test_filter_judge.py: test_sdk_filter_refuses_a_label_judge (whole, FJ-D2: the Filter judge= parameter); the ReduceNode('filter') row of test_sdk_filter_score_judge_without_judge_is_refused; the node/block tail of test_sdk_filter_judge_without_score_judge_where_is_refused (3 raises).
- test_judge_order.py: the ReduceNode('judge') rows of test_sdk_judge_label_refuses_an_order (1) and test_sdk_judge_refuses_an_unknown_order (1 per param, 5 ids); the judge block tail of test_url4_round_trip_rebuilds_an_order_min_judge_and_judge_block (4 asserts).
- test_judge_template_v2.py::test_a_reader_reads_a_min_judge_as_the_same_judge (whole: the reader min-judge normalization `_reader_judge`, no public path since the swap).
- test_judge_blocks.py: test_every_op_table_row_matches_its_named_form [label-bare-same, scores-params-override], test_judge_block_canonical_form_equality_and_hash, test_judge_block_rejects_a_bad_judge_or_rubric_or_mode (whole); the block lines of test_judge_equality_and_hash_keep_the_param_value_types (3 asserts).
- test_pick_by_signal.py: test_argmax_block_matches_pick[min-cost_usd], test_argmax_block_canonical_form (whole: the argmax block); test_pick_by_signal_validation keeps only the score:judge row (8 PickNode/block raises go: deleted Pick parameters); test_pick_by_signal_value_equality_repr_and_python (the field order form: 2 asserts); test_argmax_round_trips_through_url4_and_recovers_as_pick (the BK#8 block tail: 2 asserts).
- test_pick_output.py: test_block_output_with_a_bad_name_raises_before_any_call, test_block_forms_round_trip_to_the_named_pick_with_output (whole: the pick_field/argmax blocks); the field order rows of test_pick_without_output_compiles_the_same_select_args (3 asserts incl. _python) and test_sdk_pick_output_compiles_the_select_arg (the order-max spec pair -> the equals pair; 4 block asserts go); the _python assert of test_pick_repr_and_python_show_the_output; test_a_rebuilt_pick_refuses_an_output_that_is_not_a_field_name moves to the equals spec.
- test_pick_merge_reducers.py: the 4 PickNode field-order validation rows of test_pick_validates_its_arguments (marked group F in 7d group 1); test_pick_and_merge_repr_round_trip_and_compare_by_field (the 2 order picks of the repr list, the Merge _python assert).
- test_pick_merge_url4_round_trip.py::test_a_pick_spec_edited_by_hand_is_refused (4 ids): moved from the field order form to the equals form (sf.First), same edits.
- test_rank_by_signal.py: test_reduce_top_k_block_equals_sf_rank[min], test_reduce_top_k_block_canonical_form_equality_and_hash, test_a_block_path_option_is_capped_at_256_characters_with_the_op_table_message[top_k-by_field-options0, pick_field-field-options1] (whole: the top_k/pick_field blocks); the by_field rows of test_the_max_default_keeps_the_old_bytes_of_rank_by_field_and_by_judge (2 asserts), test_the_order_option_of_by_field_and_by_judge_writes_the_order_into_top_k_only (3 asserts), test_rank_by_signal_validation (1 RankNode by_field + 1 block raise), test_rank_by_signal_fields_repr_and_equality (2 _python, 1 by_field repr, 1 by_field inequality; the field tuple drops by_field); test_an_accounting_key_emits_sources_through_the_signal_seam[cost_usd] (the block tail: 1 assert).
- test_rank_concat_reducers.py::test_rank_needs_exactly_one_ranking_source (whole: the RankNode by=/by_field=/by_signal= sources, marked group F)
- test_rank_concat_url4_round_trip.py: the "rank by field" and "rank by field min" shapes (and `_after_node`). [7e review fix 4] tamper rows: `k is a string` and `k above the member count` move to the "rank by signal" shape; `path is not a string` DELETED; `normalizer is not pinned to the exact id` DELETED (spec gap: a rank by signal or by judge has no normalize step, so the row has no shape to move to). [7e review fix 3b] the SelfCorrective row of test_a_followed_selection_inside_a_corrective_loop_round_trips comes back on `sf.Rank(1, by="field:s")`.
- test_reducer_recovery_preference.py::test_recovered_spec_prefers_named_class_else_reduce (9 ids): the `_python()` assert reads the repr (the old renderer is gone); same expected text without "sf.".
- test_reducer_slot.py::test_fusion_accepts_a_reducer_in_the_synthesizer_slot: the 2 FusionNode._repr_html_ asserts (fusion_card_html deleted).
- test_surface_cards.py::test_e5_a_chain_member_of_todays_fusion_shows_as_a_nested_chain (whole: fusion_card_html deleted).
- e2e (the context block form, FR-2): e2e/harness/fusion_golden.py::FusionLaneSpec.build_block; e2e/test_fusion_replay.py the "block" entry of FORMS (FORMS goes; test_fusion_regression_replay_is_byte_identical loses its form parameter and the FR-2 url4 assert); e2e/fixtures/fusion_lane.py `_refuse_unless_block_matches`, the block replay in `_replay_recipe`, the tests-dir sys.path line; e2e/test_fusion_lane_contracts.py::test_a_block_form_that_matches_the_named_form_is_accepted, ::test_a_block_form_that_differs_refuses_the_bless[url4, output, digests]; module docstrings of test_fusion_golden_contracts.py / test_fusion_lane_contracts.py.
- test_pick_merge_url4_round_trip.py::test_a_pick_spec_edited_by_hand_is_refused gains the [blank value] row (the one PickNode equals check a hand url4 still reaches).

### 7e review fixes (commit `f646dcb2d`)

- `test_filter_judge.py`: new row `test_a_judge_filter_whose_where_no_longer_reads_the_judge_does_not_rebuild` (the tamper case of the deleted `test_filter_block_and_repr_rebuild_the_judge_filter`, exact "filter spec ... cannot rebuild").
- `test_rank_concat_url4_round_trip.py`: the SelfCorrective row comes back on `sf.Rank(1, by="field:s")`; `k is a string` and `k above the member count` move to the "rank by signal" shape; `path is not a string` and `normalizer is not pinned to the exact id` are deleted (listed in 7f above: a rank by signal or judge has no normalize step).
- `test_swap_prep.py`: the `sf.signal is sf.signal` tautology goes (new file in the range).
- `test_fusion_shortcut.py` (new file): the redundant url4 compare goes; frozen rows for the Gate, Merge and JudgePick shortcuts; the optional open chain refusal.

## 7g and 7h edits (commits `612de2367`, `418dcd729`, `55ceee454`, `3b44475b5`, `28bfdf77b`)

- 7g pinned messages: each edit swaps an old message fragment for its 7g text (Fusion -> sf.Fanout or fanout block, synthesizer -> the writer, Pick -> ArgMax/ArgMin/First, returns= -> sf.Judge/sf.JudgePick, extract= -> over=, by_signal= -> by=, sf.Reduce(op) -> the step or ReduceNode); no assert count changes.
- Product gap b: `test_judge_writer_warning.py` MESSAGE_BLOCK / MESSAGE_PANEL and `test_chain_warnings.py::test_e6_the_judge_and_writer_inside_one_block_still_warn` pin the in-block warning by "stage N (a fanout block)", not the inferred block name; new rows for gaps a and b in `test_judge_writer_warning.py`.
- 7h LO-P3: `test_surface_parity.py` folds `test_lop2_a_field_pick_example_compiles_to_todays_by_signal_bytes` [readme-418, readme-528] into `test_lop1_doc_example_compiles_to_the_bytes_of_today` (they equal their goldens now) and adds `test_lop3_*` for S5, S7, S10, S10', S11, S11' and S5 == S8.
- 7h rg check: docstrings and comments that named `sf.Pick` / `sf.Reduce`; `test_signal_sum_api._recipe_r(terminal=)`.
