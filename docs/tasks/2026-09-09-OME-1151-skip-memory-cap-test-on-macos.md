---
id: OME-1151
linear_url: https://linear.app/openmined/issue/OME-1151/engine-test-suite-goes-red-on-a-mac-so-the-pre-push-hook-rejects-every
status: in_progress
type: fix
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-09
closed:
---

# Engine test suite goes red on a Mac, so the pre-push hook rejects every push

`test_worker_child_memory_cap` (OME-1089) caps a child's memory via
`resource.setrlimit(RLIMIT_AS, ...)`. Linux lets a process lower its own ceiling; macOS
refuses (`ValueError: current limit exceeds maximum limit`), so the child dies for the
wrong reason and the test fails even on clean `main` — and the pre-push hook's red gate
then rejects every push from a Mac. The worker only deploys in Linux containers, so the
fix is a non-Linux `skipif` guard on the test; Linux CI keeps running it unskipped.

Ledger: `docs/work/2026-09-09-OME-1151-skip-memory-cap-test-on-macos.md`
