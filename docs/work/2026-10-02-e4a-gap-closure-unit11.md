---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-02
finished: 2026-10-02
---

# e4a-gap-closure unit 11 -- the e2e replay lanes: signals, traces, Fusion regression

## Intent

Fold the e2e replay lane (`e4a-e2e-replay`) into the gap-closure stack. The branch is rebased onto
`e4a-rank-concat-sdk`. Three rows land on top of the EV-10 and EV-12 lane: FR#13 (a GSM8K Fusion
regression lane: the same url4, outputs and request body digests), SG#15 (a cost-weighted vote replayed from cache gives the same
signals and tally) and RT#16 (the cached replay's trace differs from the live trace only in
model-call accounting). The paid recordings are made later by the user. Until then every e2e replay
test SKIPS loudly. No source file changes: this unit is tests, harness, fixtures, CI and docs.

## Planned changes

- Commit B: repair the lane tests onto the Answer-row evidence wire (unit 4).
- Commit C: pin an answered Case in the vote lane evidence lock (F3).
- Commit D: the lane snapshots carry `metadata_json` (F4, F13).
- Commit E: `harness/replay_trace.py`, the RT-4 drift rule.
- Commit F: the cost-weighted vote beside the GSM8K vote lane (record and bless seams).
- Commit G: the replay tests for signals and traces (skip until recorded).
- Commit H: `harness/fusion_golden.py` and its models.
- Commit I: `fixtures/fusion_lane.py`, `inspect_capture_stack`, and the lane tests.
- Commit J: the workflow and justfile for the fusion lane.
- Commit K: this ledger, closed.

## Test plan

Rebase. `git rebase --onto e4a-rank-concat-sdk 877f17a26 e4a-e2e-replay` replayed the 9 commits with
no textual conflict. The pre-check (`git diff --stat 877f17a26 e4a-rank-concat-sdk -- <the unit
paths>`) was empty. The parent then moved from `f7e161494` to `441b9653a` (7 review-fix commits), and
`git rebase --onto e4a-rank-concat-sdk f7e161494 e4a-e2e-replay` replayed all 19 commits again with
no conflict. The workflow and justfile diffs against the parent equal the unit's own hunks.

Red set after the first rebase (`pytest tests/e2e tests/test_corrective_vote_contract_fixture.py`
in the SDK, and the engine corrective rounds test):

| # | Observed | Fix |
|---|---|---|
| S1 | `test_reducer_golden_contracts.py` and `test_reducer_lane_contracts.py` fail at collection: `ImportError CombineMemberReading` | B |
| S2 | after S1: `_evidence()` has no `result` or `dropped`, status `"voted"` | B |
| S3 | the failure code `combine_no_votes` in the test data | B |
| S4 | does NOT apply: the EV-10 drift guard is green after the rebase | none |
| S5 | the engine test `test_corrective_loop_with_a_reducer_member_reports_no_operation_evidence_yet` stays green | none |

With the two broken files ignored: 119 passed, 25 skipped. Engine corrective rounds: 1 passed.

Commits and rows (SDK paths under `packages/screamingface/tests/e2e/`):

| Commit | Row | Test (file) | RED |
|---|---|---|---|
| B | S1-S3 | the repair of the two lane test files | none (repair) |
| C | 1 | `test_the_pinned_evidence_skips_an_abstained_first_case` (lane contracts) | yes: case 1 returned |
| C | 2 | `test_evidence_lock_refuses_an_abstained_pinned_case` (golden contracts) | yes: wrong message |
| C | 3 | `test_evidence_lock_wants_the_result_member_to_be_the_chosen_member` | yes: did not raise |
| D | 4 | `test_lane_snapshots_use_the_gateway_column_layout` | yes: 12 columns |
| D | 5 | `test_record_and_slice_sql_select_the_metadata_last` (2 cases) | yes |
| E | 6 | `test_identical_traces_have_no_drift` | guard, passes at once |
| E | 7 | `test_model_call_accounting_may_differ` (5 keys) | guard, passes at once |
| E | 8 | `test_any_other_difference_is_drift` (12 cases), plus order and count tests | yes (stub) |
| F | 9 | `test_build_with_cost_weights_compiles_a_signal_vote` | yes |
| F | 10 | `test_signal_lock_refuses_an_unpriced_recording` | yes |
| F | 11 | `test_golden_needs_both_live_traces` | yes (2 of 3 cases; "unknown key" is refused by the model at once) |
| F | 12 | `test_assert_signal_replay_*` (4 tests) | yes |
| F | 13 | `test_a_replay_with_other_signals_refuses_the_bless` and 3 more refusals | yes |
| F | 14 | `test_a_trace_drift_refuses_the_bless` and the five-path count test | yes |
| F | 15 | `test_record_runs_the_signal_vote_first_and_the_plain_vote_second`, `test_record_writes_the_seven_recording_files` | yes |
| F | 16 | `_recording()`, `_report()` and `_write_recording()` gain the signal fields | in place |
| G | e2e | `test_reducer_replay.py`: 3 tests on one module fixture | skip until recorded |
| H | 17 | `test_named_and_block_forms_compile_to_one_url4` | guard, passes at once |
| H | 18 | `test_build_uses_seeded_samples_and_the_recipe_synthesizer` | passes at once (the models are real, the stubs are the two checks) |
| H | 19 | `test_body_digests_keep_key_order_and_count_duplicates` | yes (stub) |
| H | 20 | `test_assert_fusion_replay_names_an_output_or_body_drift` (and the added/lost Case test) | yes (stub) |
| H | 21 | `test_golden_validates_and_refuses_bad_shapes` (12 cases), `test_load_fusion_golden_*` | passes at once |
| I | 22 | `test_fusion_lane_contracts.py`: the refusals of `_refuse_unless_reproduced` (6) and `_refuse_unless_block_matches` (3) | yes (stub) |
| I | 22 | the record gates, the seed refusals, the recording refusals, the capture stack | by mutation (see Notes) |
| I | 23 | `test_record_arguments_default_to_the_documented_lane` | by mutation |
| I | 24 | `test_fusion_replay.py::test_fusion_regression_replay_is_byte_identical` (4 cases) | skip until recorded |
| J | - | workflow and justfile | no test |

## Notes

Decisions F1-F14 come from the unit spec (`gap-unit11-replay.md`). The ones that need a record:

- F1 no textual conflict on either rebase. The breaks are semantic (S1-S3).
- F2 the evidence wire moved in unit 4. `_evidence()` is rebuilt on `CombineAnswerRow` and
  `CombineResult`. The "chose no member" test now uses a built answer (`built=True`, no member),
  because the constructor refuses an answered result that is not the chosen member.
- F3 pin the first Case whose evidence has `result.status == "answered"`.
- F4 the replay snapshots drop `metadata_json`, so a hit has no price and no latency. The reducer
  and fusion lanes use 13 columns. `screamingface-tests.yml` gets the aigateway snapshot path (F13).
- F5 SG#15 rides on the EV-12 recording: `record` runs the cost-weighted vote first.
- F6 RT#16 uses the live `trace_dict()` that `record` saves. A drift path is reported at key level
  (`...entries[2].signal`); a differing count, label, Case id, kind or key set is reported at its
  own level and not walked deeper.
- F7 request bodies are captured on replay only (`inspect_capture_stack`, and `fusion_lane bless`).
- F11 a bless refusal on SG-D1 or RT-4 is a product defect report, not a recording mistake.
- F12 the golden size cannot be measured before a recording exists. Record it after the bless.
- F14 EV-10 is a CHAR test: it is unchanged and green after the rebase (S4 did not apply).
- Follow-ups file `gap-sdk-followups-from-engine.md`: it has no item tagged 11. The shared helpers
  `reducer._decoded` and `_signal_world.run_candidate` (with `on_request`) have no use in this unit.

Deviations from the spec:

- D1 (F3) the answered check is its own helper, `_check_answered`, called BEFORE `_check_readings`,
  not inside `_check_text`. With the check inside `_check_text`, an abstained pinned Case fails on
  "agreement must be in (0, 1]" first, so the message "did not answer" would never show.
- D2 (F8) the recipe synthesizer is a NAMED Pipeline (`name="check"`). Unit 10S documents (F11 in
  `test_fusion_recipe.py`) that `sf.Pipeline` flattens an unnamed nested Pipeline, so
  `Pipeline([Fusion(m, Reduce("context")), Pipeline([A, B])])` means `[Fusion(m, A), B]`. That
  compiles to another url4 than `Fusion(m, Pipeline([A, B]))` (ids `synthesis_1` against `model_4`),
  so the FR-2 guard (row 17) failed for the spec's unnamed form. A named Pipeline round-trips.
- D3 (DRY) `reducer_lane._refuse_unless_board_reproduced` is the first six checks of
  `_refuse_unless_reproduced`, and `_write_fixtures` takes `lane` and `golden_kind`, so the fusion lane
  reuses both. `replayed_combines` moved to `reducer_golden.py` (the lane and the golden share it).
  The review fix round went further: `rl._record_stack(assets_root, work_dir, run)` is the one boot
  for both record lanes, `rl._read_report` reads a saved report for both, `load_golden` and
  `lane_remediation` serve both golden models, `assert_outputs` serves both the golden check and the
  bless refusal, and `harness/benchmark_assets.py` holds the assets root.
- D4 `_author_golden(report, signal_report, recording, statuses)` has a new signature,
  `_record_run` returns `(signal_report, report)` and `_record_stack` returns
  `((signal_report, report), rows)`. The tests that called the old forms were changed in place.
- D5 (Commit I) the script, its read and CLI parts and the contract tests were written together.
  Only the two refusal functions were stubbed (RED). For the other rows, each of 10 mutations of
  `fusion_lane.py` (no missing-file check, no board check, no kind check, no limit check, no seed
  check, one recipe only, no `candidate.json`, no paid gate, two changed defaults) turns a test red.
- D6 `just` is not installed here, so `just --list` was not run. The recipes copy the shape of the
  reducer lane recipes, and the `check yaml` hook passes on the workflow.
- D7 the engine venv had lost its extras after a plain `uv sync`, which made pyright fail on
  `tests/unit/inspect/test_combine_grader_parity.py` (missing `inspect_ai`). `uv sync --offline
  --extra benchmarks` restored it, and the engine gates are green.

## Review fix round

- M4 KNOWN GAP: the lanes prove SG-D1 end to end for `cost_usd` only. `metadata_json` also carries
  latency and tokens, but no candidate reads `latency_ms` or the token signals. The comments in
  `reducer_lane.py` say so.
- N1 CHOICE: the exception is recorded, `observed_at` is not normalized. `metadata_json` is TEXT, a
  jsonb round trip rewrites its bytes, and the SQL cannot be tried before a recording exists. Bless
  compares neither the evidence nor the trace rule against `cache.observed_at`.
- N3 RISK: `trace_drift` matches Cases by index, so Cases returned in completion order would make a
  correct replay fail at `case_id`.
- N4: `body_digests` is a canonical JSON digest (parsed and re-encoded), not a digest of wire bytes.

## Recording the lanes

The two lanes are recorded by the USER, later, as paid OpenRouter runs. No agent runs `record`.
From `packages/screamingface`, after the assets are prepared once:

```
(cd ../../apps/screamingface-engine && uv sync --extra benchmarks && \
  uv run python -m screamingface_engine.benchmarks.prepare \
    --root ~/.screamingface/benchmark-assets --bundle inspect-gsm8k)
export OPENROUTER_API_KEY=...  SCREAMINGFACE_RECORD_PAID=1
```

COST: use a cheap flash-tier model that accepts `seed`. With a frontier model the lane costs more
than $0.10. The vote lane makes about 100 live misses, and the Fusion lane about 25.

EV-12 (the vote lane; SG#15 and RT#16 ride on it). `record` now runs the cost-weighted vote FIRST,
then the plain vote (same member requests, so the same spend), and writes 7 files: `report.json`,
`signals-report.json`, `trace.json`, `signals-trace.json`, `candidate.json`, `recording.json`,
`cache.sql.gz` (13 columns; it prints how many rows carry `metadata_json`).

```
uv run python tests/e2e/fixtures/reducer_lane.py record \
    --model openrouter/<seed-capable-model> --samples 5 --temperature 0.7 --limit 20 \
    --out ~/sf-recordings/gsm8k-vote
uv run python tests/e2e/fixtures/reducer_lane.py bless --recording ~/sf-recordings/gsm8k-vote
```

Fusion regression lane (FR#13). 5 cases x 2 shapes, at most 35 short calls.

```
uv run python tests/e2e/fixtures/fusion_lane.py record \
    --model openrouter/<seed-capable-model> --samples 3 --temperature 0.7 --limit 5 \
    --out ~/sf-recordings/gsm8k-fusion
uv run python tests/e2e/fixtures/fusion_lane.py bless --recording ~/sf-recordings/gsm8k-fusion
```

The same steps are the `just e2e-record-reducer-lane`, `e2e-bless-reducer-lane`,
`e2e-record-fusion-lane` and `e2e-bless-fusion-lane` recipes. Then run
`SCREAMINGFACE_TEST_E2E=1 uv run pytest tests/e2e/test_reducer_replay.py tests/e2e/test_fusion_replay.py -rs -v`.

The 3 + 3 fixture files to commit afterwards (`tests/e2e/fixtures/`):

- `snapshots/inspect-gsm8k-vote.snapshot.gz`, `snapshots/inspect-gsm8k-vote.manifest.json`,
  `goldens/inspect-gsm8k-vote.reducer-golden.json`;
- `snapshots/inspect-gsm8k-fusion.snapshot.gz`, `snapshots/inspect-gsm8k-fusion.manifest.json`,
  `goldens/inspect-gsm8k-fusion.fusion-golden.json`.

A bless refusal on SG-D1 ("the cached replay's signals or tally differ from the live run's") or on
RT-4 ("the replay trace drifted outside model-call accounting") is a DEFECT REPORT about a product
(for example the hit accounting leaves `provider` None, or `metadata_json` does not certify the
price). One golden holds EV-12, SG#15 and RT#16, so a refusal blocks all three on purpose. Do not
weaken the check: report the drifted path.

## Outcome

Loud skips with `SCREAMINGFACE_TEST_E2E=1 pytest tests/e2e/test_reducer_replay.py
tests/e2e/test_fusion_replay.py -rs`: 3 + 4 skipped, each naming the missing snapshot and golden.
Example: `lane 'inspect-gsm8k-fusion' has no recorded fixtures yet: missing ...snapshot.gz,
...fusion-golden.json. They come from a paid OpenRouter recording the user runs
(tests/e2e/fixtures/fusion_lane.py: `record`, then `bless`); this skip is the honest state, never a
pass.`

Focused run: `pytest tests/e2e tests/test_corrective_vote_contract_fixture.py`: 287 passed, 31
skipped. Engine corrective rounds: 1 passed. `fusion_lane.py --help` works, and `record --model x
--out /nonexistent` is refused with `SCREAMINGFACE_RECORD_PAID=1 not set` and creates nothing.

Gates with `--base e4a-rank-concat-sdk`, on parent `441b9653a`: `screamingface` and
`screamingface-engine`, each with the append-only check (no offender) and with `--skip-append-only`,
all green; `repo` green. No file under `src/` changed, and no test file that exists at `4eca379d1`
changed.

Errata for the orchestrator: F4 (the e2e snapshots lacked `metadata_json`), F5 (SG#15 rides on the
EV-12 recording), F7 (body capture on replay only), and D2 (an unnamed Pipeline synthesizer has no
block form, so the recipe shape is a named Pipeline).
