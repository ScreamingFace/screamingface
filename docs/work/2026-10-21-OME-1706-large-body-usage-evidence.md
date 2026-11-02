---
ticket: OME-1706
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-21
finished: 2026-10-21
---

# OME-1706-large-body-usage-evidence — keep the exact cost for large successful bodies

## Intent

A successful OpenRouter body over `MAX_RAW_EVIDENCE_BYTES` (256 KiB) lost its exact cost: the hook
dropped the raw body, `usage_and_source` fell back to `provider_converted_response`, and
`_direct_cost` returned `unavailable` for that source. The Engine then left the call unpriced.
The owner chose (2026-10-21) to read only the usage fields from a larger body, not to raise the cap.

## Planned changes

- `apps/aigateway/src/aigateway/core/usage_accounting/hooks.py` — `MAX_USAGE_EVIDENCE_BYTES`
  (8 MiB) for 2xx bodies; over 256 KiB keep only `_USAGE_EVIDENCE_FIELDS` (`id`, `model`, `usage`).
  Error bodies keep the 256 KiB cap (the 429 zero-insurance proof reads every field).
- `apps/aigateway/docs/usage-accounting.md` — the bounds paragraph.
- Tests: `tests/unit/usage_accounting/test_handler.py`,
  `tests/unit/usage_accounting/test_succeeded_attempt_cost_route.py`.

## Test plan

- Large 2xx body: evidence is exactly `{id, model, usage}`, cost is a `Decimal`, latency recorded,
  capture `complete`.
- Large 2xx body with a duplicate `usage` key: no evidence, capture `partial`.
- Large 429 body: still refused at 256 KiB.
- 2xx body over 8 MiB: no evidence, latency `None`, capture `partial` (existing test, cap moved).
- End to end: bytes → `_read_body` → OpenRouter mapper → renderer gives
  `succeeded_attempt_direct_cost.status = "reported"`.

## Outcome

- **Commits:** squash-merged as `476c0cc03` (#1520) from `dd33d434b` fix(aigateway): keep exact
  usage evidence for large successful bodies, `3ba5359be` docs(aigateway): document the usage-only
  read for large successful bodies, and `ae84ad4ee` (the `docs/tasks` mirror and this ledger).
- **Gates:** ruff check, ruff format --check, pyright (0 errors), check_no_enterprise, pytest with
  coverage → 6014 passed, 0 failed, 105 skipped.
- **RED proof:** the end-to-end test fails on `origin/main` with `status: "unavailable"` and passes
  with the fix.
- **Deviations:** the existing test `test_an_oversized_body_is_not_retained_and_latency_is_null`
  now pads past `MAX_USAGE_EVIDENCE_BYTES` (its intent is unchanged: a body over the cap is not
  retained). The 8 MiB value is an agent choice, reported to the owner.
