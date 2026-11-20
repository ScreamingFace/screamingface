---
ticket: OME-1994
stack: screamingface
status: done
started: 2026-11-20
finished: 2026-11-20
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
- `packages/screamingface/scripts/check_notebooks.py`: `detach=True` joins the story markers, so the
  notebooks keep showing it.

## Test plan

- `scripts/check_notebooks.py` passes (the notebook matches the builder; every story marker,
  `detach=True` included, appears).
- Every code cell of `21_runs.ipynb` parses.
- The paid cells stay off by default (`RUN_DETACHED = False`, `REATTACH_RUN_ID = None`).

## Acceptance

- Section 7 runs end to end against an Engine with E5 P2: a detached Run starts, and after a kernel
  restart `wait()` returns its Report. Checked in the E5 P2 handover.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger.
- **Commits:** one.
- **Gates:** `check_notebooks.py` exit 0; all 13 code cells parse; ruff and ruff format clean on
  both scripts. Only `21_runs.ipynb` changed among the notebooks. CI runs the rest.
- **Deviations:** none. The section is 7, at the end, so restarting the kernel does not cut the
  earlier sections short.
