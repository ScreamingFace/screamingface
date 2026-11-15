---
ticket: OME-1925
stack: screamingface-engine
status: done
started: 2026-11-15
finished: 2026-11-15
---

# fix-rss-test-race — read current RSS before peak in the process-memory test

## Intent

`test_peak_reads_this_process_and_is_at_least_current` (added in #1656) reads the peak
(`ru_maxrss`) first and the current RSS afterwards, then asserts `peak >= current`. Under
xdist the process can grow between the two reads, so current exceeds the earlier peak and
the test fails (CI: `assert 324612096 >= 324947968` and two more). Reading current first
makes the comparison sound: a high-water mark read later is always >= an earlier reading.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_process_memory.py` — reorder the reads in that
  one test; the `getrusage` assertion stays; no assertion weakened.
- `.claude/test-change-approvals/<OME-N>.json` — owner approval (2026-11-15), byte-exact pin.

## Test plan

- No new production code; the change is to a test's read order (owner-approved prior-test edit).
- Run the single test 20 times in a loop; all must pass.
- Engine + repo gates green.

## Acceptance

- The test reads `current` before `peak`; `peak >= getrusage().ru_maxrss` and
  `peak >= current` both still asserted.
- Gates green; 20/20 loop passes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — the test reorder, `.claude/test-change-approvals/OME-1925.json`, this ledger, the `docs/tasks/2026-11-15-OME-1925-fix-rss-test-race.md` mirror.
- **Commits:** the single `test(engine): …` commit on `OME-1925-fix-rss-test-race` (see the PR).
- **Gates:** `run_gates.py screamingface-engine --base origin/main` ALL GATES GREEN (approved OME-1925 transition recognised); `run_gates.py repo --base origin/main` ALL GATES GREEN. Single test run 20 times: 20/20 pass.
- **Deviations:** none. AIDEV-NOTE: the kept `getrusage` assertion still reads `ru_maxrss` after `peak`; on Linux it cannot fail (peak is KiB x 1024), on macOS (both bytes) a growth between those two reads could still trip it — left unchanged per the "reorder only" scope.
