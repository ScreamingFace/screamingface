---
ticket: OME-1161
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1161 — Stream safe model-call activity

## Intent

Implement the Engine slice of the owner-approved activity contract merged in PR #885 (f0afef90). Full/off deployment policy, shared bounded activity behavior, production model-call observations and structured bridge-loss totals. No Client, URL4 or benchmark-stage implementation.

## Planned changes

- New Engine activity contract, session and operation scopes.
- Engine settings/composition, operation-capturing executor, model connector and closing diagnostics.
- Append-only unit/integration tests and issue mirror.

## Test plan

RED-first tests for scalar allowlists/privacy, priority/rate recovery, per-run isolation, fixed heartbeats, outcomes/retries, cancellation cleanup, expired context and instrument failures. Fake-provider local/hosted stream integration and deployment policy tests. Full Engine gates via run_gates.py, independent code review.

## Acceptance

Inactive activity is inert; full produces safe immutable observations on the current node. Limits suppress telemetry without affecting original work. No extra provider calls or modified results/accounting. No new persistence. Preserve existing tests and run all Engine gates.

## Outcome

- **Actual files:** new activity contract/session/scope modules; model connector, execution wrapper and generic closing-loss attributes; deployment/local/worker policy wiring; Helm value/schema/environment and operator docs; four new test files and task mirror.
- **Commits:** `378fade9` — feat: stream safe model-call activity; Refs: OME-1161. [Draft PR #897](https://github.com/ScreamingFace/screamingface/pull/897).
- **Gates:** RED tests reproduced missing producer, policy override, timer-creation fault and nested-scope isolation defects before fixes. Final `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main` passed append-only checks, Ruff lint/format, Pyright, layering and full coverage suite. All 112 chart-wiring checks passed; Helm lint and full-mode rendering passed; aggregate mode was rejected by schema as expected. 43 new tests; 2,753 collected in the full suite, 93% coverage. Pre-push gates also passed. Existing tests remain unchanged. New tests cover safe completion/refusal/failure/retry, real WebSocket delivery, independent Client decoding, cancellation/task cleanup, cross-task revocation, rolling priority boundaries/concurrent admission, privacy and three simulated days.
- **Review:** independent Standards and Spec reviews completed; fixed nested off/missing-sink retry leakage and expanded real-producer coverage. Follow-up reviews found no remaining actionable issues.
- **Wisdom:** one shared helper owns timing/validation/admission without importing URL4 or Benchmarks; producers supply safe facts through explicit emitters. No new event bus, archive, scoring path or dependency. No private payload or exception string enters activity. Deployment policy cannot be overridden by run inputs. New modules remain below 450 lines.
- **Deviations:** existing operator-only heartbeat backoff stays intact when activity is off; full mode uses a single fixed loop. This preserves existing operator behavior and tests while implementing the approved structured cadence. No Client, URL4 or benchmark-stage code changed. Delivery remains open pending PR review/merge.

## Architecture revision — complete (2026-09-10)

Owner approved replacing concrete core/activity dependencies with registered observers.
Spec: `docs/spec/2026-09-10-OME-1161-observation-seam.md`.
Plan: `docs/plan/2026-09-10-OME-1161-observation-seam.md`.

Planned files: generic observation interfaces/helpers, activity adapter and composition;
connector, executor and execution wrapper; regression tests and descriptions.
Test plan: RED on absent/failing observer behavior and architectural imports, then real
stream/regression tests, plugin deletion, cancellation/timer cleanup and full gates.
Acceptance: remove activity plus registration without core edits; preserve execution,
accounting, retries and operator diagnostics. Migrate only tests tied to the explicitly
superseded constructor/timer ownership. This approval authorizes those necessary changes.


Revision validation: 63 targeted tests pass, including 20 additional seam/removal/fault
regressions. The removal test physically omits the activity package from a copied installation,
replaces only its registration, and checks real model requests/retries, result/accounting,
provider failure, cancellation, operator diagnostics and top-level Engine composition.
Independent Standards and Spec review found a diagnostic-handler fault that could replace
execution errors; RED reproduced it, and the fix contains diagnostic faults with one warning
attempt per execution. Both follow-up reviews report no remaining confirmed findings.

Wisdom: generic observation ports are Engine-owned and stdlib-only; the activity adapter
imports the ports, never the reverse. No new dependency, event bus, URL4 behavior, persistence
or scoring change. Existing pre-PR tests are preserved. Three new-PR test files migrated
constructor/binding setup and the explicitly superseded shared-timer expectation; all original
outcome, isolation, privacy, rate and cancellation assertions remain. Full Engine gate runner passed (append-only against origin/main, Ruff lint/format, Pyright, layering, full tests/coverage). 2,773 tests collected; the new observation dispatch/adapter/registration modules have 99% combined coverage.


## Comment placement correction (2026-09-10)

Owner requested moving the misplaced JWT explanation back beside `jwt_secret`.
Move comments only, preserving field order and values. Verify Python AST equality against
HEAD and run required Engine gates. No behavioral test is warranted for comment placement.

Outcome: JWT explanation now directly precedes `jwt_secret`; the activity policy comment
stays with `activity_level`. Python AST is identical to HEAD, preserving field order and
behavior. Full Engine gate runner passed (append-only, lint, format, types, layering, tests/coverage).
