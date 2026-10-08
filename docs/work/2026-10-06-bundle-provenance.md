---
ticket: OME-1492   # filed before work start (owner-authored); this is PR 1 of 3
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
---

# bundle-provenance — every prepared bundle says where its Cases came from

## Intent

OME-1492 PR 1. Case Preparation already knows, inside the replay child, which Hugging Face
commit it read, which seed it forced and how many Samples it kept — and throws it away. A red
image build or a red paid-smoke press therefore can't say what drifted without someone
re-running the import on a laptop. This unit keeps those facts: the child returns them, the
bundle gets a `provenance.json` beside `cases.json`, the prepare CLI's summary line carries the
same block, and the paid smoke's run overview shows it per Benchmark (read from the cached
bundle, so it appears on every press, not only on a cache miss). No seal change (that is PR 2),
no Benchmark Revision moves, never any Case text in a log.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/replay_provenance.py` (new): the
  block builder and writer.
- `.../screamingface_engine_inspect/task_replay.py`: the child keeps its recorder and returns
  `{"prepared", "provenance"}`; new `replay_with_provenance` / `TaskReplay`; `replayed_cases`
  delegates; Case Preparation writes `provenance.json` before `cases.json` and adds the block to
  the summary (success and mismatch skip).
- `packages/screamingface/tests/paid/_case_provenance.py` (new) + `_publish_overview` in
  `test_imported_board_smoke.py`: the press page's "Where the Cases came from" table.
- Prior-test edits (owner-approved with the plan): `test_task_replay_assembly.py` patch target;
  `test_imported_board_smoke.py` publish call. Pinned in `.claude/test-change-approvals/OME-1492.json`.

## Test plan

- Engine, stand-in evals in a real child process (`test_task_replay.py`, appended): the block on
  disk and in the summary; the pinned commit and the forced seed with its value; excluded Samples
  counted; the block kept on a mismatch skip; no Case input or target in either.
- SDK (`test_case_provenance.py`, new): a full row; excluded counts; a block with no seeds; a
  missing file reads "not recorded"; a cut-off or wrong-shape file reads "unreadable"; rows sorted.

## Acceptance

- Ticket acceptance 1 (summary line + `provenance.json` in every Imported bundle) and 3 (no
  Case text in either) for the Imported Benchmarks; the hand-built ones are PR 3.
- The paid smoke overview lists each Imported Benchmark's provenance, "not recorded" for the rest.
- Ticket acceptance 4: every published Benchmark Revision unchanged.
- `run_gates.py screamingface-engine` and `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** `feat(screamingface-engine): keep where each Imported bundle's Cases came from`,
  plus this docs commit.
- **Gates:** `run_gates.py screamingface-engine --base <merge-base>` and
  `run_gates.py screamingface --base <merge-base>` ALL GREEN, no skip flag (append-only passes
  through the OME-1492 approvals file). The inspect lane: 1152 passed. Engine pyright also clean
  in an extra-less venv (how CI runs it). Free paid-lane tests: 43 passed.
- **Deviations:**
  - The hand-built Benchmarks get no block in this PR; owner call 2026-10-06 moves their
    preparers' blocks to OME-1492 PR 3 (ticket Delivery updated to three PRs). Their rows read
    "not recorded" until then.
  - The overview section lives in a new `_case_provenance.py`, not `_board_summary.py`, so the
    scoreboard module stays untouched.
  - Review fixes (2026-10-07, one commit): Case Preparation refuses a used bundle directory
    before it replays, so a refused re-prepare never touches the earlier label (new test); the
    SKIPPED-marker writing moved into its own helper to stay under the statement-count lint; the press reader turns a NaN or Infinity `seconds` into an "unreadable" row
    (new test); `CONTEXT.md` gains a Bundle Provenance entry, kept apart from Benchmark
    Provenance.
- **Owner-verify:** the next paid press (its asset cache key covers the inspect plugin, so it
  re-prepares and every Imported bundle gains `provenance.json`). Check that the run page shows
  "Where the Cases came from" with one row per Imported Benchmark, and that the image build log's
  summary lines carry `provenance`.
