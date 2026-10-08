# Plan — every prepared bundle says where its Cases came from (OME-1492 PR 1)

Spec: `docs/spec/2026-10-06-OME-1492-bundle-provenance.md` · ledger:
`docs/work/2026-10-06-bundle-provenance.md` · one PR, two landings in one ticket: the Engine's
inspect plugin, and the SDK's paid-smoke overview (test code only).

Nothing paid runs. The stand-in evals in `tests/unit/inspect/test_task_replay.py` run a real
child process, offline.

## Steps

Each line: step → verify.

1. **RED — the block from the stand-in evals.** Append to `tests/unit/inspect/test_task_replay.py`
   (plain `test_` functions, existing fixtures `fake_eval`, `fake_hub_eval`, `_pinned`):
   - `test_a_prepared_bundle_records_where_its_cases_came_from`: `fake_eval` → `provenance.json`
     exists, `samples == {"yielded": 2, "excluded": 0, "kept": 2}`, `pins` names both inspect
     packages, `seconds > 0`; the summary carries the same block.
   - `test_the_block_names_the_pinned_commit_and_the_forced_seed`: `fake_hub_eval` →
     `sources` pin is the pinned sha, `seeds_applied == {"shuffle_seed": <declared value>}`.
   - `test_excluded_samples_are_counted`: a declaration excluding one Sample → yielded 3, excluded 1, kept 2.
   - `test_a_mismatch_skip_still_carries_the_block` (because that's when on-call needs it).
   - `test_no_case_text_reaches_the_block_or_the_summary_line`: every stand-in input and target
     string is absent from `provenance.json` and `json.dumps(summary)`.
   → verify: they fail (no `provenance.json`, no `provenance` key).

2. **GREEN — the child returns the block.** In `screamingface_engine_inspect/task_replay.py`:
   - child: keep the recorder (`recorder = CaseSourceRecorder(...)`), count `yielded = len(task.dataset)`
     before capture, build the block with a pure helper, write
     `{"prepared": [...], "provenance": {...}}`.
   - parent: `replay_with_provenance(spec, *, timeout) -> TaskReplay` (a `NamedTuple` of `cases`
     and `provenance`) parses the new shape and adds `seconds`; `replayed_cases(spec, *, timeout)`
     returns its `.cases`.
   - `prepare_replayed_cases`: calls `replay_with_provenance`, writes `provenance.json` before
     `_write_cases`, adds `"provenance"` to the success and mismatch-skip summaries.
   - the block builder `replay_provenance(recorder, spec, yielded, kept) -> dict[str, Any]` lives
     beside the replay code (new `screamingface_engine_inspect/replay_provenance.py` if
     `task_replay.py` would pass ~400 lines), JSON-safe types only (lists, not sets).
   → verify: step 1 tests green; the whole `tests/unit/inspect` lane green.

3. **The one prior-test edit on the Engine side.** `test_task_replay_assembly.py`'s skip test
   monkeypatches `task_replay.replayed_cases`; point it at `replay_with_provenance` (same stub
   body). Pinned in `.claude/test-change-approvals/OME-1492.json` after the branch exists.
   → verify: that test green.

4. **RED — the overview section.** Append to `packages/screamingface/tests/paid/test_board_summary.py`:
   - `test_provenance_section_lists_each_imported_benchmark`: a tmp assets root with
     `inspect-race_h/provenance.json` → one line naming the repo, short commit, seed and
     "3498 of 3498 kept".
   - `test_a_block_without_seeds_or_hub_fetches_still_renders` (URL-only evals today, the
     hand-built preparers in PR 3).
   - `test_a_missing_file_reads_not_recorded`.
   - `test_an_unreadable_file_never_breaks_the_overview` (because the overview must never replace the verdict).
   → verify: fail on the missing function.

5. **GREEN — `_board_summary.py`.** `provenance_markdown(boards, assets_root) -> str`, reading
   `<assets>/<Benchmark id>/provenance.json` (bundle id == Benchmark id for every Imported
   Benchmark; the hand-built mapping is PR 3's). `_publish_overview` in `test_imported_board_smoke.py` appends it, reading the root from
   `conftest.assets_root()` (prior-test-file edit, pinned in the same approvals file).
   → verify: step 4 green; `SCREAMINGFACE_TEST_PAID=1 uv run pytest tests/paid -m "not paid"` green.

6. **Gates.** `run_gates.py screamingface-engine --base <merge-base>` and
   `run_gates.py screamingface --base <merge-base>`, no skip flag.
   → verify: both green; Engine CI pyright reproduced extra-less if the inspect extra matters.

7. **Close docs in the PR.** Ledger outcome, `docs/tasks/` mirror for OME-1492 marked
   in-progress (PR 2 still to come), owner-verify: the next paid press shows the section.

## Edge cases checked by design

- `task.dataset` with no `len()` → fall back to counting the captured Samples before
  exclusion (decided in step 2 if any stand-in eval needs it).
- A Benchmark with no Hub fetch (agieval reads URLs): `sources` still lists the URL with its pin;
  `seeds_applied` is `{}`.
- Old bundles without the file → "not recorded", never an error.
