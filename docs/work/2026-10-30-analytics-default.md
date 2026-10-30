---
ticket: OME-1768
stack: screamingface
status: in_progress
started: 2026-10-30
finished:
---

# Disclosure-gated default analytics

## Intent

Implement OME-1768 using the choices confirmed by Filip: terminal scripts qualify,
inline Colab notice, and a two-second first-evaluation wait. Filip explicitly
authorized implementation before Irina/Kevin sign-off, with comment posting gated
on his review. Local work only; no approval or rollout claim.

## Planned changes

- SDK analytics prompt, local persistence, Colab adapter, tracking and import hook.
- Analytics service conditional enrollment route and browser command.
- SDK/service tests, READMEs, spec and plan.

## Test plan

New tests first: disclosure before ID, prior opt-out, invalid settings, visible output,
first sync/async evaluation, timeout/late-reply races, server cookie checks.
Run SDK and analytics gates and Node script harnesses; no production events.

## Acceptance

Disclosed interactive users enroll; undisclosed users remain off; explicit disable
wins; analytics adds at most two seconds before the first Colab evaluation.
Existing payloads and explicit controls remain compatible.

## Outcome

- Actual files: SDK import, prompt/local/Colab/tracking modules and README;
  service bridge Python/JS and README; new default-enrollment SDK/service/browser
  tests; two existing SDK test files updated for the authorized contract reversal;
  exact test-transition manifest; spec/plan/task mirror and prior-spec amendments.
- Commits: local feature commit prepared; no push, PR, merge or Linear comment.
- Gates: both stack runners ALL GATES GREEN. SDK: lint, format, pyright,
  complete pytest suite with 97% coverage (95% floor), notebook-source check,
  build and distribution checks. Service: lock check, lint, format, pyright,
  complete pytest suite including Node bridge tests, 99% branch-aware coverage
  (95% floor), build. SDK Node browser harness: passed. Mirror-status and
  whitespace checks: passed.
- Verification environment: Python 3.13.5. Gate runner invoked with the installed
  SDK environment's Python (same runner and gates) because PEP-723 dependency
  resolution was network-blocked in the sandbox. SDK socket tests were rerun with
  local socket access after sandbox PermissionErrors; the complete rerun passed.
  DO_NOT_TRACK=1 protected the full SDK run; isolated analytics fixtures explicitly
  clear it and use synthetic/mocked transport. No deployed Colab browser smoke or
  production analytics delivery was performed.
- Deviations: user authorized local implementation before the issue's sign-off.
  The requested default reversal necessarily updates obsolete opt-in tests.
  Both components remain under the existing cross-unit issue for this local draft.
  Failure diagnostics and retries remain tracked separately in OME-1793.

## Review

Conditional enrollment is separate from explicit enable, preserving the user's
ability to reverse a decline intentionally. Existing version-1 choices/IDs remain
compatible. The service route must deploy before the SDK. The first async wait
includes executor queue delay and never repeats once setup completes or is disabled.
In-flight cross-notebook cookie ordering remains an existing limitation, documented
in the spec; no global revocation guarantee is added.

The implementation is ready for local review. Ledger/Linear remain open pending
review and landing. Filip must approve the short Irina confirmation comment before
posting; no sign-off has been represented as received.
