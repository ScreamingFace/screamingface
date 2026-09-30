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
