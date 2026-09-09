---
ticket: OME-1151
stack: screamingface-engine
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1151 — Engine test suite goes red on a Mac, so the pre-push hook rejects every push

## Intent

`test_worker_child_memory_cap` (OME-1089) fails on macOS: the exec wrapper's child calls
`resource.setrlimit(RLIMIT_AS, ...)`, which Linux permits (a process may lower its own
ceiling) but macOS refuses with `ValueError: current limit exceeds maximum limit`. The
child dies for the wrong reason, the assertion fails, and the pre-push hook's red gate
rejects every push from a Mac — even on clean `main`. The worker only deploys in Linux
containers, so the behavior under test is Linux-only; the test needs a platform guard.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_worker_child_memory_cap.py` — add a
  module-level `skipif` for non-Linux platforms, with a reason naming the macOS
  `setrlimit` refusal.

## Test plan

- Test-only change. RED evidence: the test fails on macOS on clean `main`
  (`AssertionError: assert 2 == 1`, both children dead of the `setrlimit` `ValueError`).
- GREEN: after the guard, the test reports `skipped` on macOS; full suite green.
- Linux CI keeps running it unskipped — the memory-cap invariant stays guarded where it
  deploys.

## Acceptance

- `uv run pytest` in `apps/screamingface-engine` is green on macOS (test skipped, not
  failed); no other test touched.
- The skip condition is `sys.platform != "linux"` (guards any non-Linux dev box, not just
  darwin), with a reason naming the platform difference.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the `docs/tasks/` mirror.
- **Commits:** `fix(screamingface-engine): skip the Linux-only memory-cap test off-Linux` (sha in PR)
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only check, ruff check,
  ruff format, pyright, layering, pytest with coverage ≥80; the memory-cap test reports
  `skipped` on macOS with the platform reason).
- **Deviations:** the first guard attempt rewrote the existing `pytestmark` line and the
  append-only test gate rejected it; restructured as a purely additive second
  `pytestmark` assignment wrapping the original, so no prior line changed.
