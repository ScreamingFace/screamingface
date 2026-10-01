---
id: OME-1444
linear_url: https://linear.app/openmined/issue/OME-1444/every-push-waits-on-test-suites-that-run-one-test-at-a-time
status: done
type: task
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1321
created: 2026-10-01
closed: 2026-10-01
---

# Every push waits on test suites that run one test at a time

The Engine and SDK gate test steps ran every test one after another on a single core. Both
now run with `pytest -n auto` (pytest-xdist in each dev group), so the step waits on the
slowest worker instead of the whole suite. Same tests, same coverage floors (80 Engine,
95 SDK); CI workflows unchanged.

- 2026-10-01: filed before work; PR opened from branch `OME-1444-parallel-gate-tests`, ledger
  `docs/work/2026-10-01-parallel-gate-tests.md`.
