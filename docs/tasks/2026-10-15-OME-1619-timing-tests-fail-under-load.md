---
id: OME-1619
linear_url: https://linear.app/openmined/issue/OME-1619/four-timing-tests-fail-under-a-loaded-parallel-run-and-pass-alone
status: triage
type: bug
priority: No priority
labels: [bug, repo-dev-processes]
created: 2026-10-15
closed:
---

# Four timing tests fail under a loaded parallel run and pass alone

Four tests fail now and then under `pytest -n auto` with coverage and pass alone, so a PR goes
red with no code cause and people re-run until green. The ticket lists the four.

- 2026-10-19: `test_inspect_rules_stay_linear_on_hostile_input` now checks how the read's
  cost grows from 32 KB to 128 KB, instead of a fixed 5 s of CPU
  (`docs/work/2026-10-19-hostile-input-growth-ratio.md`). The three others are still open.
