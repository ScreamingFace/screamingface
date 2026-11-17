---
ticket: OME-1925
stack: screamingface-engine
status: done
started: 2026-11-16
finished: 2026-11-17
---

# rss-peak-max — peak RSS never reads below current RSS

## Intent

`test_peak_reads_this_process_and_is_at_least_current` still failed on Linux CI after #1830 reordered the reads (#1750 run 43850040369: `assert 327237632 >= 327335936`). The cause is the kernel, not the order: `statm` sums the per-CPU RSS counters exactly, while `ru_maxrss` is `max(hiwater_rss, get_mm_rss())` with an approximate per-CPU read, and `hiwater_rss` is only updated when RSS is about to drop (`fs/proc/task_mmu.c` `task_mem` comment). Fix the API, not the test: `peak_resident_bytes()` folds in the current reading, so peak >= current always holds.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/process_memory.py`: `peak_resident_bytes(*, maxrss=None, platform=..., current=None)`; a live read also reads current; result is `max(peak, current)` when current is known.
- `apps/screamingface-engine/tests/unit/test_process_memory.py`: two appended tests (no existing test changed).

## Test plan

- `test_peak_is_never_below_a_given_current_reading`: explicit maxrss + current above/below/unknown.
- `test_the_live_peak_folds_in_the_current_reading`: stub `getrusage` below a stubbed current, reproducing the CI numbers without the kernel.

## Acceptance

- Both new tests RED on the old code, GREEN on the fix; the existing unit-normalisation test unchanged and green.
- Engine and repo gates green against origin/main; #1750's engine CI green after it merges main.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the OME-1925 mirror (back to in_progress until this merges).
- **Commits:** see PR.
- **Gates:** see PR.
- **Deviations:** none. A residual race remains only if RSS drops between a caller's own current read and the live re-read inside `peak_resident_bytes()`; not worth module state unless it shows up.
- **Merged:** #1851 as 3691bd8bc on 2026-11-17 (HupBaHa approved; CI green). OME-1925 Done.
