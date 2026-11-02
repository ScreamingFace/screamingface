---
ticket: OME-1768
stack: screamingface
status: in_progress
started: 2026-10-30
finished:
---

# Default analytics in all environments

## Intent

Implement OME-1768 using the choices confirmed by Filip: terminal scripts qualify,
inline Colab notice, and a two-second first-evaluation wait. Filip explicitly
authorized implementation before Irina/Kevin sign-off. On 2 November he authorized
opening the PR and confirmed proceeding, with the Linear decision update handled
by him. This does not claim approval from other reviewers or deployed verification.

## Planned changes

- SDK analytics prompt, local persistence, Colab adapter, tracking and import hook.
- Analytics service conditional enrollment route and browser command.
- SDK/service tests, READMEs, spec and plan.

## Test plan

New tests first: disclosure before ID, prior opt-out, invalid settings, visible output,
first sync/async evaluation, timeout/late-reply races, server cookie checks.
Run SDK and analytics gates and Node script harnesses; no production events.

## Acceptance

New installations enroll in all environments, including headless scripts; disclosure
is best effort. Every explicit opt-out wins; analytics adds at most two seconds
before the first Colab evaluation.
Existing payloads and explicit controls remain compatible.

## Outcome

- Actual files: SDK import, prompt/local/Colab/tracking modules and README;
  service bridge Python/JS and README; new default-enrollment SDK/service/browser
  tests; two existing SDK test files updated for the authorized contract reversal;
  exact test-transition manifest; spec/plan/task mirror and prior-spec amendments.
- Commits: `b0330994b` — feat(analytics): enable SDK analytics after disclosure,
  rebased onto `bc96df570` on 2 November for PR preparation. No merge or
  agent-posted Linear comment.
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

PR: https://github.com/ScreamingFace/screamingface/pull/1633

Filip confirmed proceeding and is posting the decision in Linear himself. The PR
is ready for review; ledger/Linear remain open pending review and landing.
Both full stack gates passed again after the 2 November rebase. No approval from
other reviewers or deployed Colab verification has been represented as received.

## 2 November — headless default-on revision

Filip requested default-on in every environment while respecting every opt-out,
and posted that decision in Linear. The earlier visible-disclosure gate is superseded.
Plan: remove terminal/output availability as an enrollment condition, preserve
DO_NOT_TRACK and explicit disable/decline, update regression tests and docs, run
SDK gates, then update PR #1633. The Linear description was aligned to the new
decision; Filip's comment was left unchanged.

Validation of this revision: ALL SDK GATES GREEN (lint, format, type checking,
full pytest with the 95% coverage floor, notebook checks, build and distribution). The test-first run against
the previous policy failed 12 cases as expected (68 cases total). The new coverage
checks headless subprocess import with redirected/missing/closed stderr, saved
opt-outs, truthy DO_NOT_TRACK values, and suppression of queued/new events when
DO_NOT_TRACK is set after enrollment. Tests mock the analytics sink.

Review: no schema, dependency or event-format changes. Only output-related
OSError/ValueError/RuntimeError failures are ignored when attempting the notice,
as required by the best-effort policy; setup failure visibility stays in OME-1793.
Existing preference locks and opt-out rechecks remain intact. Type checking passes
without new suppressions. The service implementation is unchanged by this revision;
its previously passing full gates remain applicable.

Revision commit: `feat(analytics): enable defaults in headless environments`.
Confidence review: ready for code review; deployed Colab smoke remains a rollout check.
