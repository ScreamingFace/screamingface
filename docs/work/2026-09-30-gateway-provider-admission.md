---
ticket: OME-1162
stack: aigateway
status: done
started: 2026-09-30
finished: 2026-09-30
---

# gateway-provider-admission

## Intent

Split PR #1151 into independent draft PRs based on main, as requested by the owner.
Check monotonic admission/caller deadlines after acquiring capacity. Run dispatch in the request task and let the disconnect watcher cancel that task immediately. Preserve classified errors, logging, and slot cleanup.

## Planned changes

- Import only apps/aigateway changes from reviewed commit 09a0379e.
- Add regression coverage for the reviewed behavior and record the component contract.
- Retain the existing OME-1162 child under OME-886; no duplicate tickets.

## Test plan

Run regression tests first, then stack lint, format, type, architecture, full offline
coverage suite, and Python 3.12/3.13 race checks for Gateway. No paid provider calls.

## Acceptance

Component-only implementation diff; draft PR based on main; Gateway precedes Engine.
No expired/disconnected queued call dispatches; independent timeout phases and bounded retries.

## Outcome

- **Actual files:** Gateway-only runtime/configuration, provider-admission contract, tests, and component SDLC records. Added seven race/classification regression cases.
- **Commit:** `fix(gateway): bound provider phases and prevent stale waiter dispatch`.
- **RED:** Original implementation failed four race cases (queue expiry, caller expiry, and immediate/suspended provider dispatch after disconnect). An additional overlapping-budget test exposed lost caller-deadline classification before the final fix.
- **Gates:** `PYTEST_ADDOPTS='-m "not live and not needs_postgres"' uv run .claude/scripts/run_gates.py aigateway --base 09a0379e`: ALL GATES GREEN (lint, format, Pyright, enterprise import guard, full offline coverage suite). Focused admission plus external review/socket tests: 33 passed on each of Python 3.12 and 3.13.
- **Deviations:** Append-only baseline is the previously reviewed PR head; the original 504 timeout-status assertion is retained because timeout classification is the intended contract. Live/Postgres tests are excluded as in offline CI; no paid calls.
- **Wisdom review:** Absolute deadline checks release already-acquired slots; dispatch stays in its request task, eliminating the cancellation coordination gap. No new dependencies, credential changes, or Engine runtime in this PR. Deploy before Engine #1152.

## Review follow-up: preserve timeout accounting

- **Cause:** Normalizing provider timeouts to a plain HTTPException erased the exception-type evidence used by attempt accounting, changing `transport_timeout` to generic `transport_error`.
- **Fix:** Share a safe `ProviderExecutionTimeout` HTTPException subtype between provider transport timeouts and Gateway execution-budget expiry. The wire response remains 504 / `provider_execution_timeout`; accounting retains timeout identity without exposing provider text.
- **Regression:** Add route-level tests with a real accounting collector and an observed fake send for HTTPX, LiteLLM, and Gateway execution-budget timeouts. All three failed before the fix; all pass afterward. Existing tests remain unchanged.
- **Focused validation:** 568 admission/accounting/error-policy tests passed on Python 3.13; 28 admission/accounting tests passed on Python 3.12. The original independent base/head reproducer now passes all four cases. Eight independent socket/backoff checks passed. No paid provider calls.
- **Full validation:** All Gateway gates passed with live/Postgres cases excluded, including append-only verification against `9909f372`, Ruff lint/format, Pyright, enterprise import guard, and the full offline suite with the 80% aggregate coverage floor.

## Whole-PR review follow-up

- Re-reviewed the complete diff against `2adc7a9f` for standards and specification compliance. No additional production defect or justified structural rewrite was identified; admission owns phase timing/disconnect handling and concurrency owns slot acquisition/release.
- Retained seven localhost HTTP regression cases in the repository, covering disconnects in both phases with and without the actual auth-disabled middleware, timeout wire responses, trace headers, and capacity recovery. Retained two additional unit cases for execution-budget clamping and expiry during overload backoff.
- The 37 admission/accounting/HTTP cases passed on Python 3.12 and 3.13. Tests use fake providers and loopback sockets only.
- All offline Gateway gates passed, including append-only verification against `b727e2a1`, lint/format, type checking, enterprise import guard, and aggregate coverage. Live-provider and Postgres checks remain outside this local validation.
- Clarified Gateway-versus-Engine test ownership in the contract. Rewrote the PR description around final behavior, scope, rollout, and retained tests; corrected the existing timeout-policy assertion's original status from the stale 502 claim to 408.
