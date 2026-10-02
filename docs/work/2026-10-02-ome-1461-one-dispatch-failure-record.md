---
ticket: OME-1461
stack: aigateway
status: done
started: 2026-10-02
finished: 2026-10-02
---

# ome-1461-one-dispatch-failure-record — one record per dispatch failure, even when the handler raises

## Intent

OME-968 (#1204) made every non-streaming dispatch failure emit exactly one terminal record from
`_safe_dispatch_failure_response`. When `_dispatch_failure_response` itself raises (credential
marking fails), the request emits TWO ERROR records ("dispatch failure handling error" then
"dispatch failed"). Fold the secondary failure into the single `dispatch failed` record as an
`outcome=handler_error handler_type=<Class>` field, and set the log level per the policy below
so overload and client-disconnect volume does not page anyone.

## Log-level policy (decision, OME-1461)

Applies to the terminal `dispatch failed` record only (`log_dispatch_failure`):

| status | level | why |
|---|---|---|
| 499 (`client_disconnected`, arrives with #1153 / OME-1162) | INFO | The client left; nothing failed that an operator can act on, and it is not a gateway or provider fault. Kept at INFO (not dropped) so a disconnect storm is still countable. |
| 429 | WARNING | Back-pressure, not breakage: rate-limited upstream (after the retry loop) or admission shedding. One record per rejected call under overload is expected volume; WARNING keeps it visible to WARNING+ alerting without paging on ERROR. |
| 503 | WARNING | Same overload semantics as 429 (retryable, `Retry-After`): #1153's `provider_queue_timeout` admission shedding, or an upstream 503 that survived the retry loop. Deliberately status-keyed, not classification-keyed, so both sources get one rule. |
| other 5xx | ERROR | unchanged (OME-968) — gateway/provider breakage. |
| other 4xx | WARNING | unchanged (OME-968). |
| any, `outcome=handler_error` | by final status (502 → ERROR) | the handler failing is a gateway bug; the rendered status is the sanitized 502. |

Not changed: 529 (Anthropic overloaded) stays ERROR — not in this ticket's scope; flagged as a
possible follow-up. Per-retry `aigw upstream overload` WARNINGs in `core/retry.py` are untouched.

## Planned changes

- `apps/aigateway/src/aigateway/routes/chat_dispatch.py` — `_safe_dispatch_failure_response`
  stops logging on its own and passes `handler_error_type` to `log_dispatch_failure`, which
  gains the `outcome=` field and the status→level table above.
- `apps/aigateway/tests/unit/test_dispatch_failure_records_handler_error.py` — new tests only.
- Not touched: `routes/chat.py` (call sites already pass through the funnel); no prior test edited.

## Test plan

- RED: handler raises (`record_dispatch_failure` raises `RuntimeError(PROVIDER_TEXT)` on a 401)
  → exactly one WARNING+ record, ERROR, `outcome=handler_error handler_type=RuntimeError`,
  `status=502`, call id stamped, no provider text / exc_info.
- RED: a normal mapped failure carries `outcome=mapped`.
- RED: level table — 499 → INFO (and zero WARNING+ records end-to-end), 429/503 → WARNING,
  500/502 → ERROR, 403 → WARNING (parametrized on `log_dispatch_failure`).

## Acceptance

- One record per failing request on the handler-raises path; existing OME-968 tests unchanged
  and green; `run_gates.py aigateway` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `routes/chat_dispatch.py` (fold + `_record_level`), new
  `tests/unit/test_dispatch_failure_records_handler_error.py` (12 tests), this ledger, mirror
  `docs/tasks/2026-10-02-ome-1461-one-dispatch-failure-record.md`. `routes/chat.py` untouched.
- **Commits:** `fix(aigateway): keep dispatch failures at one record when the handler raises`
  (single commit on the branch).
- **Gates:** `run_gates.py aigateway` → ALL GATES GREEN (append-only check, ruff, format,
  pyright, check_no_enterprise, pytest cov ≥80).
- **Deviations:** every `dispatch failed` record now carries `outcome=mapped|handler_error`
  (additive field). An upstream 503 that survives the retry loop drops from ERROR to WARNING —
  intended by the status-keyed policy. Overlap: open PR #1153 (OME-1162) edits the
  `_dispatch_with_backpressure` / import hunks of the same file; this change touches only
  `_safe_dispatch_failure_response` and `log_dispatch_failure`, so the hunks do not intersect.
