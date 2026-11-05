---
ticket: OME-1620
stack: screamingface
status: done
started: 2026-11-05
finished: 2026-11-05
---

# sdk-notebook-targets — every Benchmark notebook picks local or hosted with one variable

## Intent

After PR 4 a researcher can run every Benchmark on their own `screamingface up` stack, or on
the hosted Engine. The notebooks did not say which one they used: most called `sf.connect()`
unconfigured, so the SDK picked a running local stack and otherwise fell back to the hosted
Engine without a word. A researcher who forgot `up` ran hosted and did not notice. This unit
puts one `TARGET` variable in every Benchmark notebook, defaulting to `"local"`, and splits
each "Before running" section into Local and Hosted. Rides #1675, PR 4 of 4 (OME-1620).

## Planned changes

- `scripts/build_notebooks.py`: `_TARGET_SETUP` (the switch cell) and `_before_running(...)`
  (the setup section), used by the quickstart and the 12 Benchmark notebooks; notebook 18
  gains `"hosted"` beside its `local` and `dev`; notebook 12 drops its env-var route.
- `examples/*.ipynb`: regenerated.
- `tests/test_notebook_targets.py` (new).

## Test plan

- Every Benchmark notebook has exactly one TARGET cell, defaulting to `"local"`.
- Running it with `local` configures `127.0.0.1:9108`/`:9106`; with `hosted`,
  `fusion.screamingface.ai`/`leaderboard.screamingface.ai`; a typo raises.

## Acceptance

- New test passes; the notebook test files stay green; `check_notebooks.py` clean; ruff clean.

## Outcome

- **Actual files:** as planned. 01 (Client tour), 02 (connection) and 14 (report accounting)
  are left alone on purpose: 01 and 02 teach Client construction and `sf.configure`
  themselves, and 14 needs no Engine.
- **Gates:** `tests/test_notebook_targets.py` 13 passed (one per Benchmark notebook);
  mutation check: one notebook defaulting to `"hosted"` fails it. The 8 notebook test files:
  100 passed. `check_notebooks.py` clean; ruff check + format clean.
- **Deviations:** none. After main merged in (#1680), its new `19_map_select_reduce` notebook got the same switch and a Before running section: it evaluates `inspect-gsm8k` through the default client, so it had the same silent fallback.
- **Not checked:** the hosted path end to end (it needs a login, and its runs are paid), and
  whether production serves every Benchmark these notebooks name.
