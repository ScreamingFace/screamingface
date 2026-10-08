---
ticket: OME-1458
stack: screamingface-engine
status: done
started: 2026-10-08
finished: 2026-10-08
---

# attempts-importer-mapping — an inspect Task's any-match epochs import as Attempts (PR 7 of 7)

## Intent

The last PR of OME-1458 (plan `docs/plan/2026-10-08-OME-1458-attempts-per-case.md`, PR 7,
box ②). PR 2 refused every `epochs` > 1 because there was nowhere to send a second Attempt. With
PRs 3–6 built, a Task whose every reducer is any-match at N (`max`, `at_least_1`, `pass_at_N`)
imports as `attempts=N`; every other reducer stays refused by name (spec §2.6, F1 → F2). This PR
closes the ticket and its docs.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py` — `task_attempts`
  replaces `_refuse_several_epochs`.
- `.../import_replay.py` — `TaskReplayFacts.attempts`.
- `.../task_replay_rows.py` — write `attempts=N,` on the row only above 1.
- `.../benchmarks.py` — `BenchmarkSpec.attempts`, `_attempts_pins`.
- `.../single_shot.py` — the declaration and the Attempt loop from the row.
- `apps/screamingface-engine/docs/importing-an-inspect-eval.md` — the two `epochs` rows.
- Tests: `tests/unit/inspect/test_importer_refuses_epochs.py` (changed), `test_imported_attempts.py` (new).
- Closing docs: the mirror (`done`), the spec status (`implemented`), this ledger.

## Test plan

- Import: `pass_at_2`, `max` and `at_least_1` map to 2, 2, 3 Attempts; `pass_at_1` over 5 epochs
  refused by name; one `mean` among any-match reducers refuses the Task; no reducer → `mean`
  refused; one epoch imports as before with `attempts == 1`.
- Row and assembly: the row carries `attempts=2` and evaluates back; a one-Attempt row's text is
  unchanged; the revision moves only above 1; an Attempts row declares and asks N times; a
  one-Attempt row asks once.

## Acceptance

- Spec acceptance 6. `test_published_revisions.py` passes unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the PR.
- **Gates:** `pytest tests/unit` with the inspect extra: 6012 passed, 6 skipped; inspect lane
  1264 passed; `pyright` 0 errors; ruff clean.
- **Deviations:** (1) `test_importer_refuses_epochs.py`'s first test changes, as the plan said:
  it pinned #1295's refusal of `Epochs(2, "pass_at_2")`, which this PR replaces with the mapping.
  The file is new against main, so the append-only gate does not flag it and no approval
  manifest entry is needed. (2) **Review fixes.** The name alone was not the rule:
  `at_least(1, value=0.5)` is logged as `at_least_1`, so any reducer parameter other than `k`
  at full marks is now refused, naming it. A Task with any-match epochs and several scores
  (Named Scores) is refused at import, where both facts are known, instead of by the marking
  room after every Case was paid for N times. The refusal tests now also cover `at_least_2`,
  `pass_at_5` at 2 epochs and an eval's own reducer.
- **Owner-verify:** release the SDK (#1303), deploy the gateway (#1304), deploy the Engine
  (#1305, #1306, #1307),
  then one paid run of an Attempts Benchmark twice to watch the rerun replay every Attempt
  (OME-1476, ARC-AGI-2, is the real one). Linear status moves to Done by hand when this merges.
