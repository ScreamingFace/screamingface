---
ticket: OME-949
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-08-22
finished: 2026-08-22
---

# OME-949 — Cut runner default result inline cap to 512 KiB for NATS envelope headroom

Linear: https://linear.app/openmined/issue/OME-949/cut-runner-default-result-inline-cap-to-512-kib-for-nats-envelope

## Intent

A run whose aggregated result lands in roughly (0.94 MiB, 1.00 MiB] fails deterministically
at its FINAL frame with `nats: maximum payload exceeded`, after all model spend. The inline
cap gates on the raw result, but the broker carries the CloudEvent envelope (~+6% measured);
with the default cap equal to the broker's 1 MiB `max_payload` default, that window cannot
publish. Halve the default inline cap to 512 KiB so the shipped default leaves double the
measured envelope cost as headroom; results above it spill to the artifact store, which the
SDK redeems transparently. Product link: benchmark campaigns on the shared cluster stop
losing finished runs at the last step (full diagnosis: `issue.md` on the test branch).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/job_env.py` —
  `DEFAULT_RESULT_INLINE_CAP_BYTES` 1,048,576 → 524,288; docstring records the measured
  envelope inflation and the failing window it removes.
- `apps/screamingface-engine/tests/unit/test_runner.py` — new tests (RED first): pin the new
  default; pin the invariant the default protects (inline cap + envelope headroom ≤ broker
  1 MiB default); executor boundary — a ~0.6 MiB result must take the artifact path.

## Test plan

- `test_default_result_inline_cap_leaves_broker_headroom` — new default is 524,288 AND
  `DEFAULT_RESULT_INLINE_CAP_BYTES + headroom(6%) ≤ 1,048,576` (the property; the exact
  default value is pinned so a future bump fails loudly with the broker limit beside it).
- Executor boundary: result of ~0.6 MiB (old cap's "fits inline" window, new cap's spill
  zone) is delivered via artifact reference, not inline body.

## Acceptance

- RED confirmed first (tests fail against the current 1 MiB default), then GREEN.
- All prior tests green and unmodified.
- `run_gates.py screamingface-engine` all gates green.
- OME-949 mirror in `docs/tasks/` and this ledger's Outcome filled.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except the new tests live in their own file
  `tests/unit/test_result_inline_default_headroom.py` (cleaner append-only than appending to
  `test_runner.py`; zero prior files touched).
  - `apps/screamingface-engine/src/screamingface_engine/job_env.py` (default + docstring)
  - `apps/screamingface-engine/tests/unit/test_result_inline_default_headroom.py` (new)
  - `docs/tasks/2026-08-22-OME-949-result-inline-cap-headroom.md` (mirror)
- **Commits:** (see below)
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN (ruff check, ruff format,
  pyright, layering, pytest+cov≥80; append-only test check vs HEAD). Full suite 1,979 passed,
  5 skipped; +2 new tests, 0 prior modified.
- **Deviations:** test file location (above); RED confirmed first — both tests failed against
  the 1 MiB default for the right reasons (value pin; 0.6 MiB body delivered inline).
  GREEN after the one-constant change. One lint fix (import order) during the gate pass,
  attempt 2 of ≤10.
