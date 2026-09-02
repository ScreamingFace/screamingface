---
ticket: OME-1087
stack: url4
status: in_progress
started: 2026-09-02
finished:
---

# OME-1087 — Correct the JobRunner capacity contract in the streaming port

## Intent

`JobRunnerAtCapacity`'s docstring claims a cluster-backed runner never raises it.
That sentence is false and load-bearing: OME-1064 named it as the reason the
503 + `Retry-After` backpressure path was disabled for the one runner that needed
it. The queue-backed runner of OME-1086 raises it too, on queue depth. Rewrite the
docstring so it states the real rule — any substrate with a finite declared
ceiling raises it — and record in the `JobStatus` docstring that `scheduled`
already means "accepted, not yet started" (queued), so nobody adds a `queued`
member later.

## Planned changes

- `packages/url4/src/url4/streaming/interfaces/jobs.py` — rewrite the
  `JobRunnerAtCapacity` docstring; extend the `JobStatus` docstring.
- `packages/url4/tests/unit/test_jobs_port.py` — RED test asserting the docstring
  no longer contains the cluster-backed carve-out.
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` — comment
  only: fix the same false claim repeated at the 503 mapping.

## Test plan

- RED: assert `JobRunnerAtCapacity.__doc__` does not contain the cluster-backed
  carve-out and does state the general rule. Guards against a revert.
- Existing `test_jobs_port.py` stays green.

## Acceptance

- The port docstring and the two adapter implementations agree.
- `ruff` + `pyright` + `pytest` green for `packages/url4` (cov >= 95).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/url4/src/url4/streaming/interfaces/jobs.py` (docstrings),
  `packages/url4/tests/unit/test_jobs_port.py` (new RED test),
  `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` (comment only),
  `docs/work/2026-09-02-OME-1087-jobrunner-capacity-contract.md` (this ledger).
- **Commits:** <sha — message>
- **Gates:**
  - url4: ruff check pass, ruff format pass (112 files), pyright 0 errors,
    pytest 1167 passed, cov 97.55% (>= 95).
  - engine: ruff check pass, ruff format pass (348 files), pyright 0 errors,
    check_layering OK, pytest 2283 passed / 5 skipped, cov 91.66% (>= 80).
- **Deviations:** none. Note: `docs/spec/2026-09-01-OME-1065-quota-admission.md` still
  quotes the old false claim; it is a historical spec artifact and was left untouched
  (out of scope).
