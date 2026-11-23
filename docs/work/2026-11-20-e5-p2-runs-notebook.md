---
ticket: OME-1994
stack: screamingface
status: in_progress
started: 2026-11-20
finished:
---

# e5-p2-runs-notebook — show detaching a Run in the Runs notebook

## Intent

E5 P2 (OME-1837) lets `sf.evaluate(..., detach=True)` return a Run at once and be picked up later
from any machine. The Runs demo notebook (`examples/21_runs.ipynb`, OME-1910's handover notebook)
only described detach in text. This adds a section that does it, so Product can try the P2
headline in the E5 P2 handover, the way OME-1910 did for P1.

## Planned changes

- `packages/screamingface/scripts/build_notebooks.py`: `_runs()` gains section 7, "Detach and come
  back later" (paid, off by default): start a detached Run with a 2 h `deadline`, then, in a fresh
  kernel or on another machine, `sf.runs.get(REATTACH_RUN_ID).wait()` for its Report. The intro and
  section 1 point to it.
- `packages/screamingface/examples/21_runs.ipynb`: regenerated from the builder.
- `packages/screamingface/scripts/check_notebooks.py`: requires section 7's own code and rejects every
  paid flag left on (see the review rounds below).
- `packages/screamingface/README.md`: the `21_runs.ipynb` entry mentions the detach section.

## Test plan

- `scripts/check_notebooks.py` passes (the notebook matches the builder; every story marker and
  section 7's code markers appear; no paid flag is on).
- Every code cell of `21_runs.ipynb` parses.
- The paid cells stay off by default (`RUN_DETACHED = False`, `REATTACH_RUN_ID = None`).

## Acceptance

- Section 7 runs end to end against an Engine with E5 P2: a detached Run starts, and after a kernel
  restart `wait()` returns its Report. Checked in the E5 P2 handover.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger, `tests/test_check_notebooks.py` and four tests in
  `tests/test_runs_notebook.py`.
- **Commits:** three: the section, then one per review round.
- **Gates:** `check_notebooks.py` exit 0; all 13 code cells parse; ruff and ruff format clean on
  both scripts. Only `21_runs.ipynb` changed among the notebooks. CI runs the rest.
- **Deviations:** none. The section is 7, at the end, so restarting the kernel does not cut the
  earlier sections short.

## Review round 1 — HupBaHa, 2026-11-20 (changes requested)

- **The check did not pin section 7.** `detach=True` was already in section 1's text, and the
  story markers search every cell, so the check passed with section 7 removed; the paid-call guard
  rejected only `RUN_EVALUATION = True`. `check_notebooks.py` now requires two fragments only
  section 7's code has (`RUN_DETACHED = False`, `sf.runs.get(REATTACH_RUN_ID).wait()`), checked
  against code cells alone, and rejects every paid flag left on (`RUN_EVALUATION`,
  `RUN_DETACHED`). The ineffective `detach=True` marker is gone.
- **Tests:** new `tests/test_check_notebooks.py` (the generated notebooks pass; the check fails
  without section 7, and with `RUN_DETACHED = True`; both failure cases failed on the old check),
  and two tests appended to `tests/test_runs_notebook.py` (section 7 starts nothing by default;
  reattaching needs an explicit Run id).
- **Gates:** `test_check_notebooks.py`, `test_runs_notebook.py` and `test_example_notebooks.py`
  28 passed; `check_notebooks.py` exit 0; ruff, ruff format and pyright clean on the changed files.

## Review round 2 — owner's `/code-review`, 2026-11-20

- **A second paid Run (important).** Following section 7 (set `RUN_DETACHED = True`, restart, then
  run all) started another detached Run. `REATTACH_RUN_ID` now lives in section 7's first cell, and
  that cell starts a Run only when `RUN_DETACHED` is on and no id is set.
- **The paid-flag guard** now covers `REPLAY_RESULT` too, matches a flag switched on however it is
  written (spacing, a type annotation, a trailing comment), and runs before the code-marker check,
  so switching `RUN_DETACHED` on reads as a paid flag.
- **Section 7:** defines its own `MODEL`; the reattach cell turns an unknown id or a failed Run into
  a message or the partial Report; the text says another machine needs `TARGET = "hosted"`.
- **Tests:** `test_check_notebooks.py` flips the flags in place (four ways to write
  `RUN_DETACHED = True`, plus `RUN_EVALUATION` and `REPLAY_RESULT`); `test_runs_notebook.py`'s
  section-7 tests check the 2 h `deadline`, that a set id starts no Run, that `wait()`'s Report is
  shown, and that an unknown id reads as a message. All ten failed on the previous builder and check.
- **Gates:** `test_check_notebooks.py`, `test_runs_notebook.py` and `test_example_notebooks.py`
  35 passed; `check_notebooks.py` exit 0; ruff, ruff format and pyright clean on the changed files.
- **Status:** left `in_progress` until the handover runs section 7 end to end (Acceptance).
