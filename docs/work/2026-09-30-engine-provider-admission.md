---
ticket: OME-1163
stack: screamingface-engine
status: done
started: 2026-09-30
finished: 2026-09-30
---

# engine-provider-admission

## Intent

Split PR #1151 into independent draft PRs based on main, as requested by the owner.
Preserve the reviewed Engine implementation: declare phase budgets, cap by caller deadline, share the existing two-attempt retry loop, and retain spend uncertainty after transport loss. Base directly on main; merge and deploy Gateway first.

## Planned changes

- Import only apps/screamingface-engine changes from reviewed commit 09a0379e.
- Add regression coverage for the reviewed behavior and record the component contract.
- Retain the existing OME-1163 child under OME-886; no duplicate tickets.

## Test plan

Run regression tests first, then stack lint, format, type, architecture, full offline
coverage suite, and Python 3.12/3.13 race checks for Gateway. No paid provider calls.

## Acceptance

Component-only implementation diff; draft PR based on main; Gateway precedes Engine.
No expired/disconnected queued call dispatches; independent timeout phases and bounded retries.

## Outcome

- **Actual files:** Engine-only implementation, configuration, tests, and component SDLC records. Added 19 regression cases for retry combinations, caller deadlines, malformed refusals, and spend uncertainty.
- **Commit:** `fix(engine): align transport with provider admission budgets`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --base 09a0379e`: ALL GATES GREEN (lint, format, Pyright, layering, full default suite with 80% coverage floor). Optional Inspect suite: 510 passed.
- **Deviations:** Append-only baseline is the previously reviewed PR head, preserving the original approved golden-request header assertion and configuration tests. No runtime behavior changes beyond the original Engine diff. Local infrastructure-dependent tests retain their skips; no paid calls.
- **Wisdom review:** HTTP remains the cross-app boundary; retry ownership and spend uncertainty are preserved. No new dependencies or abstractions. The Gateway runtime is absent from this PR; merge/deploy #1151 first.

## Review follow-up

- Reproduced seven failing cases across report classification, delayed queue-retry wakeups, overwritten HTTPX phase limits, and boolean programmatic budgets before fixing them.
- Preserve the client's connect/write/pool limits while extending only read allowance; the total attempt remains wall-clock bounded. Both queue and transport retries recheck that a full attempt still fits after backoff.
- Reject boolean budgets consistently with TOML parsing. Declare the three Gateway timeout codes plus Engine's own caller-deadline code in the report vocabulary and its SDK mirror, so Evaluation results retain the classification.
- Scope includes the matching SDK vocabulary and tests because older closed-vocabulary SDKs reject these report codes. Release the compatible SDK before or alongside Engine. Gateway dependency is replacement PR #1153, not closed #1151.
- Added report-boundary and retry/transport regression tests. The exact-vocabulary assertion in `test_failure_classes.py` intentionally adds the four declared codes; this is the only existing test changed by the review fixes. Full Engine gates therefore use the documented append-only exception for that contract update.
- Gateway #1153 rereview at `24442c77` found no new blocker; its 37 admission/accounting/socket cases passed. Seven independent combined Engine/Gateway localhost tests passed, including phase budgets, queue retries, remaining-budget propagation, and cancellation/slot recovery. No Gateway code changes were needed.
- Final validation: full Engine gates passed (lint/format, Pyright, layering, full default suite and coverage floor); 510 optional Inspect tests passed. Focused Engine cases: 67 passed on Python 3.12 and 67 plus seven combined socket cases passed on Python 3.13. SDK vocabulary/conformance: eight passed; SDK lint/format/type, notebook checks, wheel/sdist build, and distribution checks passed.
- SDK full-suite limitation: the unchanged `test_disconnect_before_terminal_state_is_an_execution_error` stalls in websocket reconnect backoff, also reproduced against base `cd2d5d78`. The complete gate run was interrupted. A separate run excluding that synchronous/asynchronous test pair passed 2,085 tests with 26 skipped, 28 deselected (including the fenced paid lane), and 96.20% coverage against the 95% floor. No production or test changes were made to hide the baseline stall.
