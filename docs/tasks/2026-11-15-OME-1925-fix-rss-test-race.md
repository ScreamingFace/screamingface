---
id: OME-1925
linear_url: https://linear.app/openmined/issue/OME-1925/fix-the-flaky-peak-vs-current-rss-test-in-test-process-memorypy
status: done
type: task
priority: 0
labels: [screamingface-engine, agentic, autonomous]
created: 2026-11-15
closed: 2026-11-15
---

# Fix the flaky peak-vs-current RSS test in test_process_memory.py

Mirror of OME-1925 (parent epic OME-1529).

**Problem.** `test_peak_reads_this_process_and_is_at_least_current` read peak RSS before current RSS, then asserted `peak >= current`. Under xdist the process grows between the reads, so the test fails (e.g. `assert 324612096 >= 324947968`).

**Fix.** Read current first, then peak. Owner-approved prior-test change (2026-11-15), reorder only.

Ledger: `docs/work/2026-11-15-fix-rss-test-race.md`.
