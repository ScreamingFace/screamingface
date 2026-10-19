---
ticket: OME-1619
stack: screamingface-engine
status: done
started: 2026-10-19
finished: 2026-10-19
---

# hostile-input-growth-ratio — check the inspect rules' growth, not a fixed CPU budget

## Intent

`test_inspect_rules_stay_linear_on_hostile_input` guards F10 and F11 of OME-1289: the inspect
numeric rules must read a hostile 256 KB line in linear time. It asserts a fixed 5 s of CPU.
Under the engine lane's `pytest -n auto` with coverage, the linear code itself costs close to
that, so the test fails on unchanged code: 9 of the last 15 failed engine runs, main included,
and 3 of 4 attempts on #1444. This unit checks the growth instead: CPU time at 4N over N stays
near 4 for linear code and near 16 for quadratic code, whatever the machine's speed.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_combine_inspect_rules.py`: the hostile-input test
  asserts growth under 8x from 32 KB to 128 KB (or under 50 ms at 128 KB); a quadratic stand-in
  pins that the check fails a quadratic rule.

## Test plan

- Both inspect rules pass on the three hostile lines (measured ratios 3.96 to 4.03).
- A deliberately quadratic stand-in fails the same check (measured ratio about 16).

## Acceptance

- The test no longer depends on absolute CPU speed; a quadratic regression still fails it.
- The test file, ruff and pyright on it are green.

## Outcome

- **Actual files:** as planned, plus the OME-1619 task mirror (the bug had none).
- **Commits:** one test commit.
- **Gates:** the test file plain (6 passed) and under `-n 8` with coverage and 12 CPU burners
  (6 of 6 runs passed); ruff check and format, and pyright on the file.
- **Deviations:** none. The ticket is the existing bug OME-1619, which lists this test among
  four; this unit fixes one, so the ticket stays open. Main's version also passed under local
  load (this laptop is fast), so the evidence for the flake is CI's history, not a local repro.
